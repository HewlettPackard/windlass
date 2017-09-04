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
    parser.add_argument('products',
                        default=windlass.api.DEFAULT_PRODUCT_FILES,
                        type=str, nargs='*',
                        help='List of products.')

    # Download or build
    # - --build-only => build development artifacts
    # - --download   => download version specific artifacts
    #               specified on cli or in pins. Version must
    #               be specified.
    # Default is to build.
    #
    # Push
    # - publish artifacts to specific locations
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--download', action='store_true',
                       help='Download versioned artifacts. This implies '
                       'no building')
    group.add_argument('--build-only', action='store_true',
                       help='Build images but does not publish them')
    group.add_argument('--push-only', action='store_true',
                       help='Publish images only')

    parser.add_argument('--no-push', action='store_true',
                        help='Under no circumstances try and push '
                        'artifacts upstream.')

    download_group = parser.add_argument_group('Download options')
    download_group.add_argument(
        '--download-docker-registry',
        default='registry.hub.docker.com',
        help='Registry of images.')
    download_group.add_argument(
        '--download-charts-url',
        help='Helm repositories.')

    push_group = parser.add_argument_group('Push options')
    push_group.add_argument('--push-docker-registry',
                            help='Registry to push images.')
    push_group.add_argument('--push-charts-url',
                            help='Helm repositories.')

    parser.add_argument('--download-version', type=str,
                        help='Specify version of artifacts.')
    parser.add_argument('--push-version', type=str,
                        help='Version to use for upload artifacts.')

    ns = parser.parse_args()

    windlass.api.setupLogging(ns.debug)

    g = windlass.api.Windlass(ns.products)

    def process(artifact, **kwargs):
        # Optimize building and pushing to registry in one call
        if not ns.push_only:
            if ns.download:
                artifact.download(
                    version=ns.download_version,
                    docker_image_registry=ns.download_docker_registry,
                    charts_url=ns.download_charts_url,
                    **kwargs)
            else:
                artifact.build()

        if not ns.no_push:
            if not ns.build_only:
                artifact.upload(
                    version=ns.push_version,
                    docker_image_registry=ns.push_docker_registry,
                    charts_url=ns.push_charts_url,
                    **kwargs)

    docker_user = os.environ.get('DOCKER_USER', None)
    docker_password = os.environ.get('DOCKER_TOKEN', None)

    failed = g.run(process,
                   parallel=not ns.no_parallel,
                   docker_user=docker_user,
                   docker_password=docker_password)

    if failed:
        logging.error('Failed to windlass: %s', ','.join(ns.products))
        exit(1)
    else:
        logging.info('Windlassed: %s', ','.join(ns.products))


if __name__ == '__main__':
    main()
