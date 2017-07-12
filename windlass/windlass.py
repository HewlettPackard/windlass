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

import windlass.api
from windlass.charts import process_chart
from windlass.products import Products


from argparse import ArgumentParser
import logging


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

    parser.add_argument('--version', type=str,
                        help='Specify version of artifacts')

    parser.add_argument('--no-docker-cache', action='store_true',
                        help='Use no-cache option in docker build')
    parser.add_argument('--docker-pull', action='store_true',
                        help='Use pull option in docker build')

    parser.add_argument('--docker-image-registry', type=str,
                        default='registry.hub.docker.com',
                        help='')

    parser.add_argument('--charts-directory', type=str, default='charts',
                        help='Path to write charts out to for processing '
                             '(default: <directory>/charts).')
    ns = parser.parse_args()

    # do any complex argument error condition checking
    if not ns.docker_image_registry and not ns.build_only:
        parser.error(
            '--artifact-image_registry required unless --build-only specified')

    if ns.build_only and ns.push_only:
        parser.error(
            "--build-only and --push-only can't be specified at the same time")

    products = Products(products_to_parse=ns.products)
    images, charts = products.images, products.charts

    g = windlass.api.Windlass(images)
    g.setupLogging(ns.debug)

    for chart_def in charts:
        process_chart(chart_def, ns)

    def process(artifact, version=None, **kwargs):
        if not ns.push_only:
            if version:
                artifact.download(**kwargs)
            else:
                artifact.build()

        if not ns.build_only:
            artifact.upload(**kwargs)

    failed = g.run(process,
                   version=ns.version,
                   docker_image_registry=ns.docker_image_registry)

    if failed:
        logging.error('Failed to windlass: %s', ','.join(ns.products))
        exit(1)
    else:
        logging.info('Windlassed: %s', ','.join(ns.products))


if __name__ == '__main__':
    main()
