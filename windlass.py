#!/bin/env python3

from argparse import ArgumentParser
from glob import glob
from multiprocessing import Process, Queue
from os import environ
from os.path import join, basename, splitext, exists
from tempfile import TemporaryDirectory
import hashlib
import os
import shutil
import subprocess

from git import Repo
from docker import from_env
from docker.errors import ImageNotFound
import yaml


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


def build_verbosly(name, path, nocache=False):
    docker = from_env(version='auto')
    bargs = load_proxy()
    stream = docker.api.build(path=path, tag=remote+name, nocache=nocache,
                                 buildargs=bargs,
                                 stream=True)
    errors = []
    for line in stream:
        data = yaml.load(line.decode())

        if 'stream' in data:
            for out in data['stream'].split('\n\r'):
                print('%s : %s' % (name, out), end='')
        elif 'error' in data:
            #print('%s ERROR: %s' % (name, data['error']))
            errors.append(data['error'])
    if errors:
        msg = 'Failed to build %s:\n%s\n\n' %(name, '\n'.join(errors))
        raise Exception(msg)
    return docker.images.get(remote+name)


def build_image_from_remote_repo(repourl, imagepath, name, tags=[],
                                 branch='master', nocache=False):
    print('%s : Building image located in directory %s in repository %s'
          % (name, imagepath, repourl))
    docker = from_env(version='auto')
    with TemporaryDirectory() as tempdir:
        repo = Repo.clone_from(repourl, tempdir, branch=branch, depth=1,
                               single_branch=True)
        image = build_verbosly(name, join(tempdir, imagepath), nocache=nocache)
        image.tag(remote + name, 'ref_' + repo.active_branch.commit.hexsha)
        image.tag(remote + name, 'branch_' + repo.active_branch.name)
    return image


def build_image_from_local_repo(repopath, imagepath, name, tags=[],
                                nocache=False):
    docker = from_env(version='auto')
    print('%s : Building image from local directory %s' %
          (name, join(repopath, imagepath)))
    repo = Repo(repopath)
    image = build_verbosly(name, join(repopath, imagepath), nocache=nocache)
    if repo.head.is_detached:
        commit = repo.head.commit.hexsha
    else:
        commit = repo.active_branch.commit.hexsha
        image.tag(remote + name, 'branch_' + repo.active_branch.name)
    if repo.is_dirty():
        image.tag(remote + name,
                  'last_ref_' + commit)
    else:
        image.tag(remote + name, 'ref_' + commit)

    return image



def pull_image(repopath, name, tags=[]):
    docker = from_env(version='auto')
    print("%s : Pulling image from %s" % (name, repopath))
    if ':' in repopath:
        repo, tag = repopath.split(':')
    else:
        print('%s : Warning image is not pinned, latest would be pulled' % name)
        repo, tag = repopath, 'latest'
    docker.api.pull(repo, tag=tag)
    image = docker.images.get(repopath)
    docker.api.tag(image.id, remote + name, tag)
    # it seems some code depends on latest tag existing
    if not tag == 'latest':
        docker.api.tag(image.id, remote + name, 'latest')
    image = docker.images.get(':'.join([remote + name, tag]))
    return image


def get_image(image_def, nocache):
    docker = from_env(version='auto')
    try:
        im = docker.images.get(image_def['name'])
        repos, tags =zip(*(t.split(':') for t in im.tags))

        if 'nowindlass' in tags:
            print('%s : Image will not be pulled or build as it has nowindlass tag'
                  % image_def['name'])
            if not remote + image_def['name'] in repos:
                docker.api.tag(im.id, remote + image_def['name'], 'latest')
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
                                             nocache=nocache)
        else:
            im = build_image_from_remote_repo(image_def['repo'],
                                              image_def['context'],
                                              image_def['name'],
                                              branch=image_def.get('branch',
                                                                   'master'),
                                              nocache=nocache)
        print('%s : Building of image completed' % image_def['name'])
    else:
        im = pull_image(image_def['remote'], image_def['name'])
    return im


def process_image(image_def, ns):
    import sys
    sys.tracebacklimit = 0

    name = image_def['name']
    if not ns.push_only:
        get_image(image_def, ns.no_docker_cache)
    if not ns.build_only:
        docker = from_env(version='auto')
        print('%s : Pushing as %s' % (name, remote+name))
        r=docker.images.push(remote + name)
        lastmsgs = []
        for line in r.split('\n'):
            if line == '':
                continue

            data = yaml.load(line)
            if 'status' in data:
                if 'id' in data:
                    msg = '%s layer %s: %s' % (name,
                                               data['id'],
                                               data['status'])
                else:
                    msg = '%s: %s' % (name, data['status'])
                if msg not in lastmsgs:
                    print(msg)
                    lastmsgs.append(msg)
            elif 'error' in data:
                raise Exception('%s ERROR when pushing: %s' %
                                (name, data['error']))
        print('%s : succssfully pushed' % name)


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
    subprocess.call(['helm', 'package', join('/sources/<dev-env>', directory, chart)])
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

    print('generated landscaper definition for {}:'.format(name))
    print(landscaper)

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

    make_landscaper_file(chart_def, '/charts/landscaper')


if __name__ == '__main__':
    parser = ArgumentParser(description='Windlass products from other repos')
    parser.add_argument('products', default=[], type=str, nargs='*',
                        help='List of products, devenv included by default.')
    parser.add_argument('--build-only', action='store_true',
                        help='Build images but does not publish them')
    parser.add_argument('--push-only', action='store_true',
                        help='Publish images only')
    parser.add_argument('--repository', type=str, default='<remote>',
                        help='Docker registry where images can be published')
    parser.add_argument('--no-docker-cache', action='store_true',
                        help='Use no-cache option in docker build')
    ns = parser.parse_args()
    products_to_build = ns.products + ['devenv']
    remote = ns.repository + '/'
    images = []
    procs = []
    for product_file in glob('/sources/<dev-env>/products/*.yml'):
        product_name = splitext((basename(product_file)))[0]
        if product_name not in products_to_build:
            print("%s will not be installed" % product_name)
            continue
        print("Windlassing images for %s" % product_name)
        with open(product_file, 'r') as f:
            product_def = yaml.load(f.read())
            print(product_def)

        if 'images' in product_def:
            for image_def in product_def['images']:
                p = Process(target=process_image,
                            args=(image_def, ns),
                            name=image_def['name'])
                p.start()
                #p.join()
                procs.append(p)
        if 'charts' in product_def:
            for chart_def in product_def['charts']:
                print(chart_def)
                process_chart(chart_def, ns)
    failed = []
    for p in procs:
        p.join()
        if p.exitcode != 0:
            failed.append(p.name)
    if failed:
        print('Tried to windlass', ','.join(products_to_build))
        print('Failed with images', ','.join(failed))
        exit(1)
    else:
        print('Windlassed', ','.join(products_to_build))
