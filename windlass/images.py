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

from docker import from_env
from windlass.tools import split_image
from git import Repo
import logging
import os

import yaml


def load_proxy():
    proxy_keys = ('http_proxy', 'https_proxy', 'no_proxy')
    return {key: os.environ[key] for key in proxy_keys if key in os.environ}


def push_image(name, imagename, push_tag='latest', auth_config=None):
    docker = from_env(version='auto')
    logging.info('%s: Pushing as %s:%s', name, imagename, push_tag)

    # raises exception if imagename is missing
    docker.images.get(imagename + ':' + push_tag)

    r = docker.images.push(imagename, push_tag, auth_config=auth_config)
    last_msgs = []
    for line in r.split('\n'):
        if line != '':
            data = yaml.load(line)
            if 'status' in data:
                if 'id' in data:
                    msg = '%s layer %s: %s' % (name,
                                               data['id'],
                                               data['status'])
                else:
                    msg = '%s: %s' % (name, data['status'])
                if msg not in last_msgs:
                    logging.debug(msg)
                    last_msgs.append(msg)
            if 'error' in data:
                logging.error("Error building image %s:%s"
                              % (imagename, "\n".join(last_msgs)))
                raise Exception('%s ERROR when pushing: %s' % (name,
                                                               data['error']))
    return True


def clean_tag(tag):
    clean = ''
    valid = ['_', '-', '.']
    for c in tag:
        if c.isalnum() or c in valid:
            clean += c
        else:
            clean += '_'
    return clean[:128]


def build_verbosly(name, path, nocache=False, dockerfile=None,
                   pull=False):
    docker = from_env(version='auto')
    bargs = load_proxy()
    logging.info("Building %s from path %s", name, path)
    stream = docker.api.build(path=path,
                              tag=name,
                              nocache=nocache,
                              buildargs=bargs,
                              dockerfile=dockerfile,
                              stream=True,
                              pull=pull)
    errors = []
    output = []
    for line in stream:
        data = yaml.load(line.decode())
        if 'stream' in data:
            for out in data['stream'].split('\n\r'):
                logging.debug('%s: %s', name, out.strip())
                # capture detailed output in case of error
                output.append(out)
        elif 'error' in data:
            errors.append(data['error'])
    if errors:
        logging.error('Failed to build %s:\n%s', name, '\n'.join(errors))
        logging.error('Output from building %s:\n%s', name, ''.join(output))
        raise Exception("Failed to build {}".format(name))
    logging.info("Successfully built %s from path %s", name, path)
    return docker.images.get(name)


def build_image_from_local_repo(repopath, imagepath, name, tags=[],
                                nocache=False, dockerfile=None, pull=False):
    logging.info('%s: Building image from local directory %s',
                 name, os.path.join(repopath, imagepath))
    repo = Repo(repopath)
    image = build_verbosly(name, os.path.join(repopath, imagepath),
                           nocache=nocache, dockerfile=dockerfile)
    if repo.head.is_detached:
        commit = repo.head.commit.hexsha
    else:
        commit = repo.active_branch.commit.hexsha
        image.tag(name,
                  clean_tag('branch_' +
                            repo.active_branch.name.replace('/', '_')))
    if repo.is_dirty():
        image.tag(name,
                  clean_tag('last_ref_' + commit))
    else:
        image.tag(name, clean_tag('ref_' + commit))

    return image


def pull_image(remote, name):
    docker = from_env(version='auto')
    logging.info("%s: Pulling image from %s", name, remote)

    imagename, tag = split_image(name)

    docker.api.pull(remote)
    docker.api.tag(remote, imagename, tag)

    image = docker.images.get(name)
    return image


def build_image(image_def, nocache=False, pull=False):
    if 'remote' in image_def:
        im = pull_image(image_def['remote'], image_def['name'])
    else:
        # TODO(kerrin) - repo should be relative the defining yaml file
        # and not the current working directory of the program. This change
        # is likely to break this.
        repopath = os.path.abspath('.')
        dockerfile = image_def.get('dockerfile', None)
        logging.debug('Expecting repository at %s' % repopath)
        im = build_image_from_local_repo(repopath,
                                         image_def['context'],
                                         image_def['name'],
                                         nocache=nocache,
                                         dockerfile=dockerfile,
                                         pull=pull)
        logging.info('Get image %s completed', image_def['name'])
    return im


def process_image(image_def, ns):

    docker = from_env(version='auto')
    name = image_def['name']
    try:
        if not ns.push_only:
            build_image(image_def,
                        ns.no_docker_cache,
                        ns.docker_pull)
        if not ns.build_only:
            if not ns.registry_ready.is_set():
                logging.info('%s: waiting for registry', name)
                ns.registry_ready.wait()
            try:
                if ns.proxy_repository is not '':
                    image_name, tag = split_image(ns.proxy_repository + name)
                    docker.api.tag(name, image_name, tag)
                else:
                    image_name, tag = split_image(name)
                push_image(name, image_name, tag)
            finally:
                if ns.proxy_repository is not '':
                    docker.api.remove_image(ns.proxy_repository + name)
            logging.info('%s: Successfully pushed', name)
    except Exception:
        logging.exception('Processing image %s failed with exception', name)
        ns.failure_occured.set()
