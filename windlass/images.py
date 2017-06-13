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

from docker.errors import ImageNotFound
from docker import from_env
from windlass.tools import guess_repo_name
from git import Repo
import logging
import os
from tempfile import TemporaryDirectory

import yaml


def load_proxy():
    proxy_keys = ('http_proxy', 'https_proxy', 'no_proxy')
    return {key: os.environ[key] for key in proxy_keys if key in os.environ}


def push_image(name, imagename, auth_config=None, push_tag='latest'):
    docker = from_env(version='auto')
    logging.info('%s: Pushing as %s', name, imagename)

    # raises exception if imagename is missing
    docker.images.get(imagename + ":" + push_tag)

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


def build_verbosly(name, path, repository, nocache=False, dockerfile=None,
                   pull=False):
    docker = from_env(version='auto')
    bargs = load_proxy()
    logging.info("Building %s from path %s", name, path)
    stream = docker.api.build(path=path,
                              tag=repository+name,
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
    return docker.images.get(repository+name)


def build_image_from_remote_repo(
        repourl, imagepath, name, repository, tags=[],
        branch='master', nocache=False, dockerfile=None, pull=False):
    logging.info('%s: Building image located in directory %s in repository %s',
                 name, imagepath, repourl)
    with TemporaryDirectory() as tempdir:
        repo = Repo.clone_from(repourl, tempdir, branch=branch, depth=1,
                               single_branch=True)
        image = build_verbosly(name,
                               os.path.join(tempdir, imagepath),
                               repository,
                               nocache=nocache,
                               dockerfile=dockerfile,
                               pull=pull)
        image.tag(repository + name,
                  clean_tag('ref_' + repo.active_branch.commit.hexsha))
        image.tag(repository + name,
                  clean_tag('branch_' + repo.active_branch.name))
    return image


def build_image_from_local_repo(repopath, imagepath, name, repository, tags=[],
                                nocache=False, dockerfile=None, pull=False):
    logging.info('%s: Building image from local directory %s',
                 name, os.path.join(repopath, imagepath))
    repo = Repo(repopath)
    image = build_verbosly(name, os.path.join(repopath, imagepath), repository,
                           nocache=nocache, dockerfile=dockerfile)
    if repo.head.is_detached:
        commit = repo.head.commit.hexsha
    else:
        commit = repo.active_branch.commit.hexsha
        image.tag(repository + name,
                  clean_tag('branch_' +
                            repo.active_branch.name.replace('/', '_')))
    if repo.is_dirty():
        image.tag(repository + name,
                  clean_tag('last_ref_' + commit))
    else:
        image.tag(repository + name, clean_tag('ref_' + commit))

    return image


def pull_image(repopath, name, repository, tags=[]):
    docker = from_env(version='auto')
    logging.info("%s: Pulling image from %s", name, repopath)
    if ':' in repopath:
        repo, tag = repopath.split(':')
    else:
        logging.info('%s: Warning image is not pinned, latest would be pulled',
                     name)
        repo, tag = repopath, 'latest'
    docker.api.pull(repo, tag=tag)
    image = docker.images.get(repopath)
    docker.api.tag(image.id, repository + name, tag)
    # it seems some code depends on latest tag existing
    if not tag == 'latest':
        docker.api.tag(image.id, repository + name, 'latest')
    image = docker.images.get(':'.join([repository + name, tag]))
    return image


def get_image(image_def, nocache, repository, repodir, pull=False):
    docker = from_env(version='auto')
    try:
        im = docker.images.get(image_def['name'])
        repos, tags = zip(*(t.split(':') for t in im.tags))

        if 'nowindlass' in tags:
            logging.info(
                '%s: Image will not be pulled or build as it has nowindlass '
                'tag', image_def['name'])
            if not repository + image_def['name'] in repos:
                docker.api.tag(im.id, repository + image_def['name'], 'latest')
            return im
    except ImageNotFound:
        pass
    tags = image_def.get('tags', [])
    if 'repo' in image_def:
        if image_def['repo'] == '.':
            repopath = './' + repodir
        else:
            repopath = './%s' % guess_repo_name(image_def['repo'])
        dockerfile = image_def.get('dockerfile', None)
        if os.path.exists(os.path.join(repopath, '.git')):
            im = build_image_from_local_repo(repopath, image_def['context'],
                                             image_def['name'],
                                             repository=repository,
                                             nocache=nocache,
                                             dockerfile=dockerfile,
                                             pull=pull)
        else:
            im = build_image_from_remote_repo(image_def['repo'],
                                              image_def['context'],
                                              image_def['name'],
                                              repository=repository,
                                              branch=image_def.get('branch',
                                                                   'master'),
                                              nocache=nocache,
                                              dockerfile=dockerfile,
                                              pull=pull)
        logging.info('Get image %s completed', image_def['name'])
    else:
        im = pull_image(image_def['remote'], image_def['name'], repository)
    return im


def process_image(image_def, ns):

    docker = from_env(version='auto')
    name = image_def['name']
    try:
        if not ns.push_only:
            get_image(image_def, ns.no_docker_cache, ns.repository, ns.repodir,
                      ns.docker_pull)
        if not ns.build_only:
            if not ns.registry_ready.is_set():
                logging.info('%s: waiting for registry', name)
                ns.registry_ready.wait()
            try:
                if ns.proxy_repository is not '':
                    image_name = ns.proxy_repository + name
                    docker.api.tag(ns.repository + name, image_name, "latest")
                else:
                    image_name = ns.repository + name
                push_image(name, image_name)
            finally:
                if ns.proxy_repository is not '':
                    docker.api.remove_image(ns.proxy_repository + name)
            logging.info('%s: Successfully pushed', name)
    except Exception:
        logging.exception('Processing image %s failed with exception', name)
        ns.failure_occured.set()
