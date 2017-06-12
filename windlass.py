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
from collections import defaultdict
import datetime
from glob import glob
import hashlib
import logging
from multiprocessing import Event
from multiprocessing import Process
import os
import os.path
import subprocess
from tempfile import TemporaryDirectory
import time

from docker.errors import APIError
from docker.errors import ImageNotFound
from docker.errors import NotFound
from docker import from_env
from git import Repo
import yaml


def guess_repo_name(repourl):
    if repourl.endswith('.git'):
        return repourl.split('/')[-1][:-4]
    else:
        return repourl.split('/')[-1]


def load_proxy():
    proxy_keys = ('http_proxy', 'https_proxy', 'no_proxy')
    return {key: os.environ[key] for key in proxy_keys if key in os.environ}


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


def push_image(name, imagename):
    docker = from_env(version='auto')
    logging.info('%s: Pushing as %s', name, imagename)

    # raises exception if imagename is missing
    docker.images.get(imagename + ":latest")

    r = docker.images.push(imagename, "latest")
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
                    elif 'error' in data:
                        logging.error("Error building image %s:"
                                      "%s", imagename, "\n".join(last_msgs))
                        raise Exception('%s ERROR when pushing: %s' %
                                        (name, data['error']))
    return True


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


def fetch_remote_chart(repo, chart, version, output_dir):
    repo_name = hashlib.sha1(repo.encode('utf-8')).hexdigest()[:20]
    subprocess.call(['helm', 'repo', 'add', repo_name, repo])

    if version:
        version_args = ['--version', version]
    else:
        version_args = []

    subprocess.call(['helm', 'fetch', repo_name+'/'+chart, '-d', output_dir] +
                    version_args)


def package_local_chart(directory, chart, repodir, chartdir):
    subprocess.call(
        ['helm', 'package',
         os.path.abspath(os.path.join(".", repodir, directory, chart))],
        cwd=chartdir)


def process_chart(chart_def, ns):

    chart = chart_def['name']
    if 'repo' in chart_def:
        package_chart(chart_def, ns.repodir, ns.charts_directory)
    elif 'remote' in chart_def:
        version = chart_def['version']
        repository = chart_def['remote']
        fetch_remote_chart(repository, chart, version, ns.charts_directory)
    else:
        errmsg = ('Chart %s has no git or helm repo defined '
                  'and cannot be processed' % chart)
        logging.error(errmsg)
        raise Exception(errmsg)


def package_chart(chart_def, repodir, chartdir):

    if chart_def['repo'] == '.':
        repopath = '.'
    else:
        repopath = guess_repo_name(chart_def['repo'])

    if os.path.exists(repopath):
        logging.info('%s: Packaging chart from local directory %s'
                     % (chart_def['name'], repopath))
        package_local_chart(os.path.join(repopath, chart_def['location']),
                            chart_def['name'], repodir, chartdir)
    else:
        with TemporaryDirectory() as tempdir:
            branch = chart_def.get('branch', 'master')
            logging.info('%s: Packaging chart from git repository %s branch %s'
                         % (chart_def['name'], chart_def['repo'], branch))
            Repo.clone_from(chart_def['repo'],
                            tempdir,
                            branch=branch,
                            depth=1,
                            single_branch=True)
            package_local_chart(os.path.join(tempdir, chart_def['location']),
                                chart_def['name'],
                                repodir,
                                chartdir)


def wait_for_registry(ns, wait=600):
    docker = from_env(version='auto')
    registry = ns.proxy_repository or ns.repository
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
                        help='List of products, devenv included by default.')
    parser.add_argument('--build-only', action='store_true',
                        help='Build images but does not publish them')
    parser.add_argument('--push-only', action='store_true',
                        help='Publish images only')
    parser.add_argument('--repository', type=str, default='',
                        help='Docker registry where images can be published')
    parser.add_argument('--proxy-repository', type=str, default='',
                        help='Alternative address to use temporarily when it '
                             'is not possible to push directly to the '
                             'repository but still useful to use the name '
                             'for images.')
    parser.add_argument('--no-docker-cache', action='store_true',
                        help='Use no-cache option in docker build')
    parser.add_argument('--docker-pull', action='store_true',
                        help='Use pull option in docker build')
    parser.add_argument('--directory', type=str,
                        default=os.path.abspath(os.path.curdir),
                        help='Directory to run windlass under, will change to '
                             'this path before processing any files '
                             '(default: %(default)s)')
    parser.add_argument('--charts-directory', type=str,
                        help='Path to write charts out to for processing '
                             '(default: <directory>/charts).')
    ns = parser.parse_args()

    # do any complex argument error condition checking
    if not (ns.repository or ns.proxy_repository) and not ns.build_only:
        parser.error("--repository (or --proxy-repository) required "
                     "unless --build-only specified")

    if ns.build_only and ns.push_only:
        parser.error(
            "--build-only and --push-only can't be specified at the same time")

    # set additional defaults based on options parsed
    if not ns.charts_directory:
        ns.charts_directory = os.path.join(ns.directory, 'charts')

    parentdir, ns.repodir = os.path.split(ns.directory)
    os.chdir(parentdir)
    level = logging.DEBUG if ns.debug else logging.INFO
    logging.basicConfig(level=level,
                        format='%(asctime)s %(levelname)s %(message)s')

    logging.info("Sources directory: '%s'", ns.directory)
    logging.info("Charts directory: '%s'", ns.charts_directory)
    ns.registry_ready = Event()
    ns.failure_occured = Event()
    if ns.repository and not ns.repository.endswith('/'):
        ns.repository = ns.repository + '/'
    if ns.proxy_repository and not ns.proxy_repository.endswith('/'):
        ns.proxy_repository = ns.proxy_repository + '/'

    if not ns.build_only:
        waitproc = Process(target=wait_for_registry,
                           args=(ns,), name='wait_for_registry')
        waitproc.start()

    images = []

    logging.info("looking for products under %s/products/*.yml", ns.directory)
    products = glob(os.path.join(ns.directory, 'products', '*.yml'))
    logging.debug("Found products: %s" % products)
    for product_file in products:
        product_name = os.path.splitext((os.path.basename(product_file)))[0]
        if product_name not in ns.products:
            logging.info("%s will not be installed", product_name)
            continue
        logging.info("Windlassing images for %s", product_name)
        with open(product_file, 'r') as f:
            product_def = yaml.load(f.read())
        if 'images' in product_def:
            for image_def in product_def['images']:
                images.append(image_def)
        if 'charts' in product_def:
            for chart_def in product_def['charts']:
                logging.debug(chart_def)
                process_chart(chart_def, ns)

    procs = []

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
