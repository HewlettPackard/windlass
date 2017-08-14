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


from argparse import ArgumentParser
import logging
import os


def main():
    parser = ArgumentParser(description='Windlass products from other repos')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--no-parallel', action='store_true',
                        help='Windlass artifacts serially. This is '
                        'helpful for debugging')
    parser.add_argument('products', default=[], type=str, nargs='*',
                        help='List of products.')

    parser.add_argument('--build-only', action='store_true',
                        help='Build images but does not publish them')
    parser.add_argument('--push-only', action='store_true',
                        help='Publish images only')

    parser.add_argument('--version', type=str,
                        help='Specify version of artifacts.')

    parser.add_argument('--no-docker-cache', action='store_true',
                        help='Use no-cache option in docker build')
    parser.add_argument('--docker-pull', action='store_true',
                        help='Use pull option in docker build')

    parser.add_argument('--docker-image-registry', type=str,
                        default='registry.hub.docker.com',
                        help='')

    parser.add_argument(
        '--charts-url', type=str,
        help='URL to publish charts to.')

    ns = parser.parse_args()

    # do any complex argument error condition checking
    if not ns.docker_image_registry and not ns.build_only:
        parser.error(
            '--artifact-image_registry required unless --build-only specified')

    if ns.build_only and ns.push_only:
        parser.error(
            "--build-only and --push-only can't be specified at the same time")

    windlass.api.setupLogging(ns.debug)

    g = windlass.api.Windlass(ns.products)

    def process(artifact, version=None, **kwargs):
        # Optimize building and pushing to registry in one call
        if not ns.push_only:
            artifact.build()

        if not ns.build_only:
            # TODO(kerrin) Should version be required?
            artifact.upload(version, **kwargs)

    docker_user = os.environ.get('DOCKER_USER', None)
    docker_password = os.environ.get('DOCKER_TOKEN', None)

    failed = g.run(process,
                   parallel=not ns.no_parallel,
                   version=ns.version,
                   docker_image_registry=ns.docker_image_registry,
                   charts_url=ns.charts_url,
                   docker_user=docker_user,
                   docker_password=docker_password)

    if failed:
        logging.error('Failed to windlass: %s', ','.join(ns.products))
        exit(1)
    else:
        logging.info('Windlassed: %s', ','.join(ns.products))


if __name__ == '__main__':
    main()
