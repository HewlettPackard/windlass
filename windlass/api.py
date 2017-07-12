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

from collections import defaultdict
import git
import logging
import multiprocessing
import os.path
import shutil
import tempfile
import urllib.parse
import yaml

DEFAULT_PRODUCT_FILES = [
    'products/products.yml',
    'products/products.yaml',
    'products.yml',
    'products.yaml',
]


class Artifact(object):
    """Artifact type

    Contains methods to control how to manage artifacts of a
    particular type.

    This includes building, publishing and downloading artifacts.

    Attributes:

    data - provides a dictionary of data set by the user to
           describe the artifact

    metadata - system specific data set by Windlass, used
               Windlass to manage the artifacts
    """

    def __init__(self, data):
        self.data = data
        self.metadata = {}

    @property
    def priority(self):
        return self.data.get('priority', 0)

    @property
    def name(self):
        return self.data['name']

    def url(self, version=None):
        raise NotImplementedError('url not implemented')

    def build(self):
        """Build the artifact

        This builds the artifact for use by a developer
        """
        raise NotImplementedError('build not implemented')

    def download(self, version, **kwargs):
        """Download the versioned artifact from central registry

        This downloads the versioned artifact and if it can, it
        will rename this version to the local development version
        so developers can get going quickly with the latest
        blessed version in there workstation.
        """
        raise NotImplementedError('download not implemented')

    def upload(self, version, **kwargs):
        """Upload chart to the artifact server"""
        raise NotImplementedError('upload not implemented')


class Artifacts(object):

    def __init__(self, products_to_parse=DEFAULT_PRODUCT_FILES):
        self.data = {}
        self.tempdir = tempfile.mkdtemp()

        self.items = self.load(
            products_to_parse,
            # Default metadata to assign to arifacts
            repopath=os.path.abspath('.'))

    def __del__(self):
        shutil.rmtree(self.tempdir)

    def load(self,
             products_to_parse=DEFAULT_PRODUCT_FILES,
             repopath=None,
             **metadata):
        artifacts = []

        for product_file in products_to_parse:
            if not os.path.exists(product_file):
                logging.debug(
                    'Products file %s does not exist, skipping' % (
                        product_file))
                continue

            with open(product_file, 'r') as f:
                product_def = yaml.load(f.read())

            # TODO(kerrin) this is not a deep merge, and is pretty poor.
            # Will lose data on you.
            self.data.update(product_def)

            for key, cls in _products_registry.items():
                if key in product_def:
                    for artifact_def in product_def[key]:
                        repourl = artifact_def.get('repo', None)
                        if repourl and repourl != '.':
                            # checkout repo and load
                            # path begins with / and can end with a .git, both
                            # of which we remove
                            path = urllib.parse.urlparse(repourl).path. \
                                rsplit('.git', 1)[0]. \
                                split('/', 1)[1]
                            destpath = os.path.join(self.tempdir, path)
                            if not os.path.exists(destpath):
                                repo = git.Repo.clone_from(
                                    repourl,
                                    destpath,
                                    depth=1,
                                    single_branch=True)

                            items = self.load(
                                map(lambda conf: os.path.join(
                                    repo.working_dir, conf),
                                    DEFAULT_PRODUCT_FILES),
                                # Override default system metadata
                                repopath=repo.working_dir,
                                **metadata
                            )

                            nameditems = [
                                item for item in items
                                if item.name == artifact_def.get('name')]
                            if len(nameditems) != 1:
                                raise Exception(
                                    'Found %d artifacts called %s in %s' % (
                                        len(nameditems),
                                        artifact_def['name'],
                                        repourl))

                            artifact = nameditems[0]
                        else:
                            artifact = cls(artifact_def)
                            artifact.metadata['repopath'] = repopath
                            artifact.metadata.update(metadata)

                        artifacts.append(artifact)

        return artifacts

    def __iter__(self):
        for item in self.items:
            yield item


class Windlass(object):

    def __init__(self, products_to_parse):
        self.artifacts = Artifacts(products_to_parse)
        self.failure_occured = multiprocessing.Event()
        # This is only used by windlass.py and should be removed?
        self.registry_ready = multiprocessing.Event()

    def wait_for_procs(self):
        while True:
            if self.failure_occured.wait(0.1):
                for p in self.procs:
                    p.terminate()
                logging.info('Killed all processes')
                return False

            if len([p for p in self.procs if p.is_alive()]) == 0:
                return True

    def work(self, process, artifact, *args, **kwargs):
        try:
            process(artifact, *args, **kwargs)
        except Exception:
            logging.exception(
                'Processing image %s failed with exception', artifact.name)
            self.failure_occured.set()

    def run(self, processor, type=None, *args, **kwargs):
        # Reset events.
        self.procs = []

        d = defaultdict(list)
        for artifact in self.artifacts:
            if type is not None and not isinstance(artifact, type):
                logging.debug(
                    'Skipping artifact %s because wrong type' % artifact.name)
                continue
            k = artifact.priority
            d[k].append(artifact)

        failed = False
        for i in reversed(sorted(d.keys())):
            for artifact in d[i]:
                p = multiprocessing.Process(
                    target=self.work,
                    args=(
                        processor,
                        artifact,
                    ) + args,
                    kwargs=kwargs,
                    name=artifact.name,
                )
                p.start()
                self.procs.append(p)
            if not self.wait_for_procs():
                failed = True

        if failed:
            raise Exception('Failed to process artifacts')

    def list(self, version=None, type=None, **kwargs):
        for artifact in self.artifacts:
            if type is not None and isinstance(artifact, type):
                yield artifact.url(version, **kwargs)

    def build(self):
        self.run(lambda artifact: artifact.build())

    def download(self, version, type=None, *args, **kwargs):
        self.run(
            lambda artifact: artifact.download(version, *args, **kwargs),
            type=type)

    def upload(self, version, type=None, *args, **kwargs):
        self.run(
            lambda artifact: artifact.upload(version, *args, **kwargs),
            type=type)


def setupLogging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level, format='%(asctime)s %(levelname)s %(message)s')


_products_registry = {}


class register_type(object):
    """All classes that implement a Artifact must be decorated with this

    This registries the class to a key in the products.yaml files. See
    windlass.images.Image for a example.
    """

    def __init__(self, key):
        self.key = key

    def __call__(self, cls):
        _products_registry[self.key] = cls
        return cls
