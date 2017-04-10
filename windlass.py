#!/bin/env python3

from collections import defaultdict
from argparse import ArgumentParser
from glob import glob
from multiprocessing import Process, Event
from os import environ
from os.path import join, basename, splitext, exists
from tempfile import TemporaryDirectory
import hashlib
import logging
import os
import shutil
import subprocess

from git import Repo
from docker import from_env
from docker.errors import ImageNotFound, NotFound, APIError
import yaml
from time import sleep


def guess_repo_name(repourl):
    if repourl.endswith('.git'):
        return repourl.split('/')[-1][:-4]
    else:
        return repourl.split('/')[-1]


def load_proxy():
    env = {}
    if 'http_proxy' in environ:
        env['http_proxy'] = environ['http_proxy']
    if 'https_proxy' in environ:
        env['https_proxy'] = environ['https_proxy']
    return env


def clean_tag(tag):
    clean = ''
    valid = ['_', '-', '.']
    for c in tag:
        if c.isalnum() or c in valid:
            clean += c
        else:
            clean += '_'
    return clean[:128]


def build_verbosly(name, path, repository, nocache=False):
    docker = from_env(version='auto')
    bargs = load_proxy()
    logging.info("Building %s from path %s", name, path)
    stream = docker.api.build(path=path,
                              tag=repository+name,
                              nocache=nocache,
                              buildargs=bargs,
                              stream=True)
    errors = []
    for line in stream:
        data = yaml.load(line.decode())
        if 'stream' in data:
            for out in data['stream'].split('\n\r'):
                logging.debug('%s: %s', name, out.strip())
        elif 'error' in data:
            errors.append(data['error'])
    if errors:
        logging.error('Failed to build %s:\n%s', name, '\n'.join(errors))
        raise Exception("Failed to build {}".format(name))
    logging.info("Successfully built %s from path %s", name, path)
    return docker.images.get(repository+name)


def build_image_from_remote_repo(repourl, imagepath, name, repository, tags=[],
                                 branch='master', nocache=False):
    logging.info('%s: Building image located in directory %s in repository %s',
                 name, imagepath, repourl)
    docker = from_env(version='auto')
    with TemporaryDirectory() as tempdir:
        repo = Repo.clone_from(repourl, tempdir, branch=branch, depth=1,
                               single_branch=True)
        image = build_verbosly(name, join(tempdir, imagepath), repository,
                               nocache=nocache)
        image.tag(repository + name,
                  clean_tag('ref_' + repo.active_branch.commit.hexsha))
        image.tag(repository + name,
                  clean_tag('branch_' + repo.active_branch.name))
    return image


def build_image_from_local_repo(repopath, imagepath, name, repository, tags=[],
                                nocache=False):
    docker = from_env(version='auto')
    logging.info('%s: Building image from local directory %s',
                 name, join(repopath, imagepath))
    repo = Repo(repopath)
    image = build_verbosly(name, join(repopath, imagepath), repository,
                           nocache=nocache)
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


def get_image(image_def, nocache, repository):
    docker = from_env(version='auto')
    try:
        im = docker.images.get(image_def['name'])
        repos, tags = zip(*(t.split(':') for t in im.tags))

        if 'nowindlass' in tags:
            logging.info('%s: Image will not be pulled or build as it has nowindlass '
                         'tag', image_def['name'])
            if not repository + image_def['name'] in repos:
                docker.api.tag(im.id, repository + image_def['name'], 'latest')
            return im
    except ImageNotFound:
        pass
    tags = image_def.get('tags', [])
    if 'repo' in image_def:
        if image_def['repo'] == '.':
            repopath = '/sources/<dev-env>'
        else:
            repopath = '/sources/%s' % guess_repo_name(image_def['repo'])
        if exists(join(repopath, '.git')):
            im = build_image_from_local_repo(repopath, image_def['context'],
                                             image_def['name'],
                                             repository=repository,
                                             nocache=nocache)
        else:
            im = build_image_from_remote_repo(image_def['repo'],
                                              image_def['context'],
                                              image_def['name'],
                                              repository=repository,
                                              branch=image_def.get('branch',
                                                                   'master'),
                                              nocache=nocache)
        logging.info('Get image %s completed', image_def['name'])
    else:
        im = pull_image(image_def['remote'], image_def['name'], repository)
    return im


def push_image(name, imagename):
    docker = from_env(version='auto')
    logging.info('%s: Pushing as %s', name, imagename)
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
            get_image(image_def, ns.no_docker_cache, ns.repository)
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
    except Exception as e:
        logging.exception('Processing image %s failed with exception', name)
        ns.failure_occured.set()


def fetch_remote_chart(repo, chart, version):
    repo_name = hashlib.sha1(repo.encode('utf-8')).hexdigest()[:20]
    subprocess.call(['helm', 'repo', 'add', repo_name, repo])

    if version:
        version_args = ['--version', version]
    else:
        version_args = []

    subprocess.call(['helm', 'fetch', repo_name+'/'+chart, '-d', '/charts'] +
                    version_args)


def package_local_chart(directory, chart):
    subprocess.call(
        ['helm', 'package', join('/sources/<dev-env>', directory, chart)])
    subprocess.call(['ls'])

    for tgz in glob(chart + '*.tgz'):
        shutil.copy(tgz, '/charts')


def make_landscaper_file(chart_def, landscaper_dir):
    name = chart_def.get("name")
    version = chart_def.get("version")
    chart = chart_def.get("chart")
    configuration = chart_def.get("configuration")

    content = {
        "name": name,
        "release": {
            "chart": "ncs/{name}:{version}".format(
                name=chart,
                version=version),
            "version": version,
        },
        "configuration": configuration,
    }

    if not os.path.exists(landscaper_dir):
        os.makedirs(landscaper_dir)

    landscaper = yaml.dump(content, default_flow_style=False)

    logging.info('generated landscaper definition for %s', name)
    logging.debug(landscaper)

    with open(join(landscaper_dir, chart_def.get("name")) + '.yaml', 'w') as f:
        f.write(landscaper)


def process_chart(chart_def, ns):
    version = chart_def['version']
    chart = chart_def['chart']
    repository = chart_def['repository']

    if repository.startswith('./'):
        package_local_chart(repository, chart)
    else:
        fetch_remote_chart(repository, chart, version)

    make_landscaper_file(chart_def, '/charts/landscaper-build')


def wait_for_registry(ns):
    docker = from_env(version='auto')
    while True:
        try:
            docker.api.pull((ns.proxy_repository or ns.repository) + 'noimage')
            ns.registry_ready.set()
            logging.info('wait_for_registry: registry detected')
            return
        except (APIError, NotFound):
            pass
        except Exception as e:
            logging.exception('wait_for_registry: Failed')
            ns.failure_occured.set()
            return
        finally:
            if ns.failure_occured.wait(0.1):
                return


def wait_for_procs(procs, ns):
    while True:
        if len([p for p in procs if p.is_alive()]) == 0:
            return True
        if ns.failure_occured.wait(0.1):
            for p in procs:
                p.terminate()
            logging.info('Killed all processes')
            return False


def main():
    parser = ArgumentParser(description='Windlass products from other repos')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('products', default=[], type=str, nargs='*',
                        help='List of products, devenv included by default.')
    parser.add_argument('--build-only', action='store_true',
                        help='Build images but does not publish them')
    parser.add_argument('--push-only', action='store_true',
                        help='Publish images only')
    parser.add_argument('--repository', type=str, default='<remote>',
                        help='Docker registry where images can be published')
    parser.add_argument('--proxy-repository', type=str, default='',
                        help='Alternative address to use temporarily when it '
                             'is not possible to push directly to the '
                             'repository but still useful to use the name '
                             'for images.')
    parser.add_argument('--no-docker-cache', action='store_true',
                        help='Use no-cache option in docker build')
    ns = parser.parse_args()

    level = logging.DEBUG if ns.debug else logging.INFO
    logging.basicConfig(level=level,
                        format='%(asctime)s %(levelname)s %(message)s')

    ns.registry_ready = Event()
    ns.failure_occured = Event()
    products_to_build = ns.products + ['devenv']
    if not ns.repository.endswith('/'):
        ns.repository = ns.repository + '/'
    if ns.proxy_repository and not ns.proxy_repository.endswith('/'):
        ns.proxy_repository = ns.proxy_repository + '/'
    images = []
    if not ns.build_only:
        waitproc = Process(target=wait_for_registry,
                           args=(ns,), name='wait_for_registry')
        waitproc.start()
    procs = []

    for product_file in glob('/sources/<dev-env>/products/*.yml'):
        product_name = splitext((basename(product_file)))[0]
        if product_name not in products_to_build:
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
        logging.error('Failed to windlass: %s', ','.join(products_to_build))
        exit(1)
    else:
        logging.info('Windlassed: %s', ','.join(products_to_build))


if __name__ == '__main__':
    main()
