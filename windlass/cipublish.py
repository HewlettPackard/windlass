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
from windlass.tools import guess_repo_name
import git
import logging
import os


def get_commit(path):
    repo = git.Repo(path)
    if repo.head.is_detached:
        return repo.head.commit.hexsha
    else:
        return repo.active_branch.commit.hexsha


def main():
    parser = ArgumentParser('Publish new artifacts')
    parser.add_argument('--docker-repo', type=str, required=True,
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
    if ns.docker_user:
        auth_config = {'username': ns.docker_user,
                       'password': ns.docker_password}
    else:
        auth_config = None

    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(levelname)s %(message)s')
    images, charts = read_products(directory=os.getcwd(),
                                   products_to_parse=ns.products)
    thisreponame = os.path.split(os.getcwd())[-1]
    for image_def in images:
        if 'repo' in image_def:
            if image_def['repo'] == '.' or \
               guess_repo_name(image_def['repo']) == thisreponame:
                fullname = ns.docker_repo + '/' + image_def['name']
                logging.info('Publishing %s' % fullname)
                docker = from_env(version='auto')
                push_tag = get_commit('.')
                docker.api.tag(image_def['name'], fullname, push_tag)
                push_image(image_def['name'],
                           fullname,
                           auth_config=auth_config,
                           push_tag=push_tag)
            else:
                logging.debug('Skipping image %s coming from other repo' %
                              image_def['name'])
        else:
            logging.debug('Skipping remote image %s' % image_def['name'])


if __name__ == '__main__':
    main()
