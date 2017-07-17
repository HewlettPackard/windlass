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
import windlass.api
import logging
import requests
import ruamel.yaml
import sys


def main():
    parser = ArgumentParser('Publish new artifacts')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--list', action='store_true',
                        help='Only list images we will be promoted')
    parser.add_argument('--docker-src-repo', type=str,
                        help='Docker repo to promote from',
                        default='staging-docker')
    parser.add_argument('--docker-dst-repo', type=str,
                        help='Docker repo to promote to',
                        default='alpha-docker')
    parser.add_argument('--docker-user', type=str,
                        help='Username if required for docker registry')
    parser.add_argument('--docker-password', type=str,
                        help='Password if required for docker registry')
    parser.add_argument('--manifest-file', type=str,
                        help='Manifest containg pins',
                        required=True)
    parser.add_argument('--artifactory', type=str,
                        help='URL to Artifactory',
                        required=True)
    ns = parser.parse_args()
    art_url = ns.artifactory if ns.artifactory[-1] == '/' \
        else ns.artifactory + '/'

    windlass.api.setupLogging(ns.debug)

    auth = (ns.docker_user, ns.docker_password) if ns.docker_user else None
    data = ruamel.yaml.load(open(ns.manifest_file),
                            Loader=ruamel.yaml.RoundTripLoader)
    pins = data['image_pins']

    logging.debug('Using artifactory at %s', art_url)
    image_url = art_url + 'api/storage/%s/%s/%s'
    for imagename, commitid in pins.items():
        # Check if image is in target repo
        resp = requests.get(image_url % (ns.docker_dst_repo,
                                         imagename,
                                         commitid), auth=auth)
        if resp.status_code == 200:
            logging.debug('%s:%s already in alpha' % (imagename, commitid))
            continue
        elif resp.status_code != 404:
            logging.error('Unexcpected code %d for %s:%s',
                          resp.status_code,
                          imagename,
                          commitid)
            logging.error('Response was:\n%s', resp.text)
            sys.exit(1)
        # Check if in source repository
        resp = requests.get(image_url % (ns.docker_src_repo,
                                         imagename, commitid), auth=auth)
        if resp.status_code == 404:
            logging.error('Image %s:%s missing from source repo',
                          imagename, commitid)
            logging.error('Response was:\n%s', resp.text)
            sys.exit(1)
        elif resp.status_code != 200:
            logging.error('Unexcpected code %d for %s:%s in source repo',
                          resp.status_code, imagename, commitid)
            logging.error('Response was:\n%s' % resp.text)
            sys.exit(1)
        if ns.list:
            logging.info('Image %s:%s would be promoted', imagename, commitid)
            continue
        promote_url = art_url + 'api/docker/%s/v2/promote' % ns.docker_src_repo
        promote_data = {'targetRepo': ns.docker_dst_repo,
                        'dockerRepository': imagename,
                        'tag': commitid}

        resp = requests.post(promote_url, json=promote_data, auth=auth)
        if resp.status_code != 200:
            logging.error('Failed to promote %s:%s from %s to %s in Artifactor'
                          'y %s', imagename, commitid, ns.docker_src_repo,
                          ns.docker_dst_repo)
            sys.exit(1)
        logging.info('Promoted %s:%s from %s to %s in Artifactory %s',
                     imagename,
                     commitid,
                     ns.docker_src_repo,
                     ns.docker_dst_repo)


if __name__ == '__main__':
    main()
