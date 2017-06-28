#!/bin/env python3
#
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#

from windlass.charts import process_chart
from windlass.images import process_image
from windlass.products import read_products


from argparse import ArgumentParser
from collections import defaultdict
import datetime
import logging
from multiprocessing import Event
from multiprocessing import Process
import time

from docker.errors import APIError
from docker.errors import NotFound
from docker import from_env


def wait_for_registry(ns, wait=600):
    docker = from_env(version='auto')
    registry = ns.proxy_repository
    timeout = datetime.datetime.now() + datetime.timedelta(seconds=wait)
    while True:
        if datetime.datetime.now() > timeout:
            ns.failure_occured.set()
            logging.exception(
                'wait_for_registry %s timeout after %d seconds' % (
                    registry, wait))
            return

        try:
            result = docker.api.pull(registry + 'noimage')
            # result is a simple string of the json response, check if either
            # the requested image was found, or explicitly "not found" to
            # determine if the docker deamon can reach the desired registry
            if ("Digest: sha256" in result or
                    "Error: image noimage not found" in result):
                ns.registry_ready.set()
                logging.info('wait_for_registry: registry detected')
                return

            time.sleep(1)
            continue
        except (APIError, NotFound):
            pass
        except Exception:
            logging.exception('wait_for_registry: Failed')
            ns.failure_occured.set()
            return
        finally:
            if ns.failure_occured.wait(0.1):
                return


def wait_for_procs(procs, ns):
    while True:
        if ns.failure_occured.wait(0.1):
            for p in procs:
                p.terminate()
            logging.info('Killed all processes')
            return False

        if len([p for p in procs if p.is_alive()]) == 0:
            return True


def main():
    parser = ArgumentParser(description='Windlass products from other repos')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('products', default=[], type=str, nargs='*',
                        help='List of products.')
    parser.add_argument('--build-only', action='store_true',
                        help='Build images but does not publish them')
    parser.add_argument('--push-only', action='store_true',
                        help='Publish images only')
    parser.add_argument('--proxy-repository', type=str, default='',
                        help='Alternative address to use temporarily when it '
                             'is not possible to push directly to the '
                             'repository but still useful to use the name '
                             'for images.')
    parser.add_argument('--no-docker-cache', action='store_true',
                        help='Use no-cache option in docker build')
    parser.add_argument('--docker-pull', action='store_true',
                        help='Use pull option in docker build')
    parser.add_argument('--charts-directory', type=str, default='charts',
                        help='Path to write charts out to for processing '
                             '(default: <directory>/charts).')
    ns = parser.parse_args()

    # do any complex argument error condition checking
    if not ns.proxy_repository and not ns.build_only:
        parser.error("--proxy-repository required "
                     "unless --build-only specified")

    if ns.build_only and ns.push_only:
        parser.error(
            "--build-only and --push-only can't be specified at the same time")

    level = logging.DEBUG if ns.debug else logging.INFO
    logging.basicConfig(level=level,
                        format='%(asctime)s %(levelname)s %(message)s')

    ns.registry_ready = Event()
    ns.failure_occured = Event()

    if ns.proxy_repository and not ns.proxy_repository.endswith('/'):
        ns.proxy_repository = ns.proxy_repository + '/'

    if not ns.build_only:
        waitproc = Process(target=wait_for_registry,
                           args=(ns,), name='wait_for_registry')
        waitproc.start()

    images, charts = read_products(products_to_parse=ns.products)

    procs = []

    for chart_def in charts:
        process_chart(chart_def, ns)

    d = defaultdict(list)
    for image_def in images:
        k = image_def.get('priority', 0)
        d[k].append(image_def)
    failed = False
    for i in reversed(sorted(d.keys())):
        for image_def in d[i]:
            p = Process(target=process_image,
                        args=(image_def, ns),
                        name=image_def['name'])
            p.start()
            procs.append(p)
        if not wait_for_procs(procs, ns):
            failed = True

    if failed:
        logging.error('Failed to windlass: %s', ','.join(ns.products))
        exit(1)
    else:
        logging.info('Windlassed: %s', ','.join(ns.products))


if __name__ == '__main__':
    main()
