#!/bin/env python3
from git import Repo
from tempfile import TemporaryDirectory
from docker import from_env
from os.path import join, basename, splitext, exists
from os import environ
from glob import glob
from argparse import ArgumentParser
from yaml import load


def guess_repo_name(repourl):
    if repourl.endswith('.git'):
        return repourl.split('/')[-1][:-4]
    else:
        raise NotImplemented


def load_proxy():
    env = {}
    if 'http_proxy' in environ:
        env['http_proxy'] = environ['http_proxy']
    if 'https_proxy' in environ:
        env['https_proxy'] = environ['https_proxy']
    return env


def build_image_from_remote_repo(repourl, imagepath, name, tags=[],
                                 branch='master'):
    print('Building image %s located in directory %s in repository %s'
          % (name, imagepath, repourl))
    with TemporaryDirectory() as tempdir:
        repo = Repo.clone_from(repourl, tempdir, branch=branch, depth=1,
                               single_branch=True)
        image = docker.images.build(path=join(tempdir, imagepath),
                                    tag=remote + name, nocache=True,
                                    buildargs=load_proxy())
        image.tag(remote + name, 'ref_' + repo.active_branch.commit.hexsha)
        image.tag(remote + name, 'branch_' + repo.active_branch.name)
    return image


def build_image_from_local_repo(repopath, imagepath, name, tags=[]):
    print('Building image %s from local directory %s' %
          (name, join(repopath, imagepath)))
    repo = Repo(repopath)
    image = docker.images.build(path=join(repopath, imagepath),
                                tag=remote + name, nocache=True,
                                buildargs=load_proxy())
    if repo.is_dirty():
        image.tag(remote + name,
                  'last_ref_' + repo.active_branch.commit.hexsha)
    else:
        image.tag(remote + name, 'ref_' + repo.active_branch.commit.hexsha)
    image.tag(remote + name, 'branch_' + repo.active_branch.name)
    return image


if __name__ == '__main__':
    docker = from_env()

    parser = ArgumentParser(description='Windlass products from other repos')
    parser.add_argument('products', default=['devenv'], type=str, nargs='*',
                        help='List of products to be windlassed')
    parser.add_argument('--build-only', action='store_true',
                        help='Build images but does not publish them')
    parser.add_argument('--repository', nargs=1, type=str,
                        default='<remote>',
                        help='Docker registry where images can be published')
    ns = parser.parse_args()
    if ns.build_only:
        remote = ''
    else:
        remote = ns.repository + '/'
    images = []
    for product_file in glob('/sources/<dev-env>/products/*.yml'):
        product_name = splitext((basename(product_file)))[0]
        if product_name not in ns.products:
            print("%s will not be installed" % product_name)
            continue
        print(product_name)
        with open(product_file, 'r') as f:
            product_def = load(f.read())
        if 'images' in product_def:
            for image_def in product_def['images']:
                repopath = '/sources/%s' % guess_repo_name(image_def['repo'])
                if exists(join(repopath, '.git')):
                    build_image_from_local_repo(repopath, image_def['context'],
                                                image_def['name'])
                else:
                    build_image_from_remote_repo(image_def['repo'],
                                                 image_def['context'],
                                                 image_def['name'],
                                                 branch=image_def.get('branch', 'master'))
                if remote:
                    print('Pushing', remote + image_def['name'])
                    docker.images.push(remote + image_def['name'])
