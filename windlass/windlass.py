#!/bin/env python3
#
# (c) Copyright 2017-2018 Hewlett Packard Enterprise Development LP
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
import windlass.pins

from argparse import ArgumentParser
import logging
import os
import sys


def process(artifact, ns, **kwargs):
    # Optimize building and pushing to registry in one call
    if not ns.push_only:
        if ns.download:
            artifact.download(
                version=ns.download_version,
                docker_image_registry=ns.download_docker_registry,
                charts_url=ns.download_charts_url,
                generic_url=ns.download_generic_url,
                **kwargs)
        else:
            artifact.build()

    if not ns.no_push:
        if not ns.build_only:
            artifact.upload(
                version=ns.push_version,
                docker_image_registry=ns.push_docker_registry,
                charts_url=ns.push_charts_url,
                generic_url=ns.push_generic_url,
                **kwargs)


def main():
    parser = ArgumentParser(description='Windlass products from other repos')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--timestamps', action='store_true',
                        help='Add timestamps to output')
    parser.add_argument('--no-parallel', action='store_true',
                        help='Windlass artifacts serially. This is '
                        'helpful for debugging')
    parser.add_argument('products',
                        default=windlass.api.DEFAULT_PRODUCT_FILES,
                        type=str, nargs='*',
                        help='List of products.')
    parser.add_argument('--product-integration-repo', type=str,
                        help='''Integration repository containing a product-integration.yaml
configuration''')

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
        '--download-docker-registry', action='append',
        default=['registry.hub.docker.com'],
        help='Registry of images.')
    download_group.add_argument(
        '--download-charts-url', action='append',
        help='Helm repositories.')
    download_group.add_argument(
        '--download-generic-url', action='append')

    push_group = parser.add_argument_group('Push options')
    push_group.add_argument('--push-docker-registry', action='append',
                            default=[],
                            help='Registry to push images.')
    push_group.add_argument('--push-charts-url', action='append',
                            default=[],
                            help='Helm repositories.')
    push_group.add_argument('--push-generic-url', action='append',
                            default=[],
                            help='Generic artifact repositories')

    parser.add_argument('--download-version', type=str,
                        help='Specify version of artifacts.')
    parser.add_argument('--push-version', type=str,
                        help='Version to use for upload artifacts.')

    parser.add_argument('--workspace', type=str,
                        help='''Declare where to find repositories. If a
repository is located in the workspace then we don't try and check it out.

If no workspace specified this defaults to the environmental variable
WORKSPACE or else if that isn't present to your parent directory.''')

    parser.add_argument('--pool-size', type=int,
                        help='''Set size of the process pool. This is the
amount of artifacts to process at any one time.''')

    ns = parser.parse_args()

    # Setup ns.workspace if it is not specified.
    # If --workspace is not specified then try the following:
    # - environmental variable WORKSPACE - default in CI
    # - the parent directory of current location
    if not ns.workspace:
        ns.workspace = os.environ.get('WORKSPACE', None)
        if not ns.workspace:
            ns.workspace = os.path.abspath(
                os.path.join(os.getcwd(), os.path.pardir))

    if len(ns.download_docker_registry) > 1:
        ns.download_docker_registry = ns.download_docker_registry[1:]
    if len(ns.download_charts_url) > 1:
        ns.download_charts_url = ns.download_charts_url[1:]
    if len(ns.download_generic_url) > 1:
        ns.download_generic_url = ns.download_generic_url[1:]

    windlass.api.setupLogging(ns.debug, ns.timestamps)

    # We have specified a product integration repository. Load all
    # artifacts from the configuration in this repository.
    if ns.product_integration_repo:
        artifacts = windlass.pins.read_pins(ns.product_integration_repo)
        g = windlass.api.Windlass(artifacts=artifacts, pool_size=ns.pool_size)
    else:
        g = windlass.api.Windlass(
            ns.products,
            workspace=ns.workspace,
            pool_size=ns.pool_size)

    docker_user = os.environ.get('DOCKER_USER', None)
    docker_password = os.environ.get('DOCKER_TOKEN', None)

    try:
        g.run(
            process,
            ns=ns,
            parallel=not ns.no_parallel,
            docker_user=docker_user,
            docker_password=docker_password)
    except windlass.exc.WindlassException:
        logging.error('Exited due to error.')
        sys.exit(1)
    logging.info('Windlassed: %s', ','.join(ns.products))


if __name__ == '__main__':
    main()
