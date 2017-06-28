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

from argparse import ArgumentParser
from docker import from_env
from windlass.images import push_image
from windlass.products import read_products
from windlass.tools import split_image
import git
import logging


def get_commit(path):
    repo = git.Repo(path)
    if repo.head.is_detached:
        return repo.head.commit.hexsha
    else:
        return repo.active_branch.commit.hexsha


def main():
    parser = ArgumentParser('Publish new artifacts')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--list', action='store_true',
                        help='Only list images we will publish')
    parser.add_argument('--docker-repo', type=str,
                        help='Docker registry name')
    parser.add_argument('--docker-user', type=str,
                        help='Username if required for docker registry')
    parser.add_argument('--docker-password', type=str,
                        help='Password if required for docker registry')
    # parser.add_argument('--helm-repo', type=str, default='helmstaging',
    #                    help='Helm repository name')
    parser.add_argument('products', default=[], type=str, nargs='*',
                        help='List of products')
    ns = parser.parse_args()

    if not ns.list and not ns.docker_repo:
        parser.error('--list or --docker-repo must be set.')

    if ns.docker_user:
        auth_config = {'username': ns.docker_user,
                       'password': ns.docker_password}
    else:
        auth_config = None

    logging.basicConfig(level=logging.DEBUG if ns.debug else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')

    images, charts = read_products(products_to_parse=ns.products)

    docker = from_env(version='auto')
    for image_def in images:
        imagename, tag = split_image(image_def['name'])
        push_tag = get_commit('.')

        if ns.list:
            print('%s:%s' % (imagename, push_tag))
            continue

        fullname = ns.docker_repo + '/' + imagename

        logging.info('Publishing %s:%s to %s:%s' % (
            imagename, tag, fullname, push_tag))

        docker.api.tag(image_def['name'], fullname, push_tag)

        push_image(image_def['name'],
                   fullname,
                   push_tag,
                   auth_config=auth_config)


if __name__ == '__main__':
    main()
