#
# (c) Copyright 2017-2018 Hewlett Packard Enterprise Development LP
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
import functools
import git
import logging
import multiprocessing
import os.path
import shutil
import tempfile
import time
import urllib.parse
import urllib3.exceptions
import yaml

DEPRECATED_PRODUCT_FILES = [
    'products/products.yml',
    'products/products.yaml',
    'products.yml',
    'products.yaml',
]

DEFAULT_PRODUCT_FILES = ['artifacts.yaml'] + DEPRECATED_PRODUCT_FILES
# Pick the first of these as the canonical name.
CANONICAL_PRODUCT_FILE = DEFAULT_PRODUCT_FILES[0]


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

    version  - default version of artifact.
               * None implies that we are managing the development version
                 of this artifact as specified in the repository or the
                 default version of this type of artifact.
               * Non-none means that we have overridden the development
                 version.

    Note that we the upload, and download method can override the default
    version. So we can publish artifacts under a unique version.

    """

    def __init__(self, data):
        self.data = data
        self.metadata = {}
        self.name = data['name']
        self.version = data.get('version', None)
        self.priority = data.get('priority', 0)

    def set_version(self, version):
        """Set vesrion of artifact.

        This is the version we will build, upload and download.
        """
        self.version = version

    def url(self, version=None):
        raise NotImplementedError('url not implemented')

    def build(self):
        """Build the artifact

        This builds the artifact for use by a developer
        """
        raise NotImplementedError('build not implemented')

    def download(self, version=None, **kwargs):
        """Download the versioned artifact from central registry

        This downloads the versioned artifact and if it can, it
        will rename this version to the local development version
        so developers can get going quickly with the latest
        blessed version in there workstation.

        version - override the default version for this operation
        """
        raise NotImplementedError('download not implemented')

    def upload(self, version=None, **kwargs):
        """Upload chart to the artifact server

        version - override the default version for this operation
        """
        raise NotImplementedError('upload not implemented')

    def update_version(self, version):
        """Update an artifact's version, rewriting it if necessary"""
        # Make the default behaviour same as set_version()
        return self.set_version(version)

    def export_stream(self, version=None):
        """Export an artifact to a stream object"""
        raise NotImplementedError('export_stream not implemented')

    def export(self, export_dir='.', export_name=None, version=None):
        """Export an artifact to a single file.

        If export_dir is set, the export file is stored there, otherwise it is
        stored in the current directory.  If export_name is set it is used as
        the name of the exported artifact.  Otherwise the export name is
        generated from the internal artifact name.

        Return the name of the export file (full path, including export_dir).
        """
        raise NotImplementedError('export not implemented')

    def export_signable(self, export_dir='.', export_name=None, version=None):
        """Export a signable representation of an artifact to a single file.

        This may be the artifact itself (e.g. a chart tarball), or it may just
        be some form of hash of the artifact.
        """
        return self.export(export_dir, export_name, version)


class Artifacts(object):

    def __init__(self, products_to_parse=None, workspace=None):
        if not products_to_parse:
            products_to_parse = DEFAULT_PRODUCT_FILES
        self.data = {}
        self.tempdir = tempfile.mkdtemp()

        self.items = self.load(
            products_to_parse,
            workspace=workspace,
            # Default metadata to assign to arifacts
            repopath=os.path.abspath('.'))

    def __del__(self):
        if os.path.exists(self.tempdir):
            shutil.rmtree(self.tempdir)

    def load(self,
             products_to_parse,
             workspace=None,
             repopath=None,
             **metadata):
        artifacts = []

        for product_file in products_to_parse:
            if not os.path.exists(product_file):
                logging.debug(
                    'Products file %s does not exist, skipping' % (
                        product_file))
                continue
            if product_file in DEPRECATED_PRODUCT_FILES:
                logging.warn('Please use "artifacts.yaml" as "%s" is '
                             'deprecated and will be removed int future '
                             'versions' % product_file)

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

                            # See if we have the remote repository checked out
                            # in the workspace, otherwise check it out.
                            destpath = None
                            if workspace:
                                local_dev_path = os.path.join(
                                    workspace,
                                    path.split('/', 1).pop())

                                if os.path.exists(local_dev_path):
                                    destpath = local_dev_path
                            if not destpath:
                                destpath = os.path.join(self.tempdir, path)
                                if not os.path.exists(destpath):
                                    git.Repo.clone_from(
                                        repourl,
                                        destpath,
                                        depth=1,
                                        single_branch=True)

                            items = self.load(
                                map(
                                    lambda conf: os.path.join(
                                        destpath, conf),
                                    DEFAULT_PRODUCT_FILES),
                                # Override default system metadata
                                repopath=destpath,
                                **metadata
                            )
                            if not items:
                                logging.warning(
                                    'No artifacts found in %s - missing %s?',
                                    repourl, CANONICAL_PRODUCT_FILE
                                )
                            nameditems = [
                                item for item in items
                                if item.name == artifact_def.get('name')]
                            if not nameditems:
                                raise Exception(
                                    'Failed to find %s in %s - check %s' % (
                                        artifact_def['name'], repourl,
                                        CANONICAL_PRODUCT_FILE))
                            elif len(nameditems) > 1:
                                raise Exception(
                                    'Found %d of %s in %s' % (
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


class Remote(object):
    def __init__(self):
        pass

    def upload_docker(self, image_name, upload_name=None, upload_tag=None):
        """Upload docker image

        """
        raise NotImplementedError('Docker upload not implemented')

    def download_docker(self, image_name):
        """Upload docker image

        """
        raise NotImplementedError('Docker download not implemented')


class NoValidRemoteError(Exception):
    """Indicate that a remote upload endpoint is not configured"""
    pass


class RetryableFailure(Exception):
    """Rasise this exception when you want to retry the task

    This will retry and task a fix number of time with a small
    time back off.
    """


class retry(object):
    """Retry decorator

    Add this decorator to any method that we need to retry.
    """

    def __init__(self, max_retries=3, retry_backoff=5):
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    def __call__(self, func):
        @functools.wraps(func)
        def retry_f(*args, **kwargs):
            artifact = args[0]
            for i in range(0, self.max_retries):
                try:
                    return func(*args, **kwargs)
                except (urllib3.exceptions.ReadTimeoutError, RetryableFailure):
                    logging.exception(
                        '%s: problem occuried retrying, backing '
                        'off %d seconds' % (
                            artifact.name, self.retry_backoff))
                    time.sleep(self.retry_backoff)

            raise Exception('%s: Maximum number of retries occurred (%d)' % (
                artifact.name, self.max_retries))

        return retry_f


class fall_back(object):
    """Fall back decorator

    This decorator will take the keys to fall back on. This means that we
    will call the decorated once for each item in the list of values passed
    as a keyword argument until it passes.

    This allows use to download proposed artifacts that haven't been promoted
    yet. We try to download the artifact from alpha registry but this can
    fail and we will fall back to downloading the artifact from staging.

    The first argument of the wrapped function must be an Artifact object.
    """

    def __init__(self, *keys, **kwargs):
        self.keys = keys
        self.first_only = kwargs.get('first_only', False)

    def __call__(self, func):
        @functools.wraps(func)
        def fall_back_f(*args, **kwargs):
            # We support falling back on multiple keys here. Collect them
            # all and call the decorated method with the i'th fall back
            # of each key
            all_fall_backs = []
            for key in self.keys:
                fall_backs = kwargs.pop(key, [])
                # if the argument isn't a list then convert it to a list
                if fall_backs:
                    if isinstance(fall_backs, list):
                        all_fall_backs.append(fall_backs)
                    else:
                        all_fall_backs.append([fall_backs])

            if not all_fall_backs:
                raise Exception('Missing arguments: %s' % ','.join(self.keys))
            for count, fall_backs in enumerate(zip(*all_fall_backs)):
                for idx, fall_back in enumerate(fall_backs):
                    kwargs[self.keys[idx]] = fall_back

                try:
                    return func(*args, **kwargs)
                except Exception:
                    logging.debug(
                        'Error getting %s, falling back to next repository' % (
                            args[0].name),
                        exc_info=True,
                    )

                    if self.first_only or count == (len(all_fall_backs[0])-1):
                        # Failed to find artifact so raise error
                        raise
                    # log error

            # No artifact found
            artifact = args[0]
            raise Exception('Failed to find artifact %s, version: %s' % (
                artifact.name, kwargs.get('version') or artifact.version))

        return fall_back_f


class DummyResult(object):

    def __init__(self, result):
        self._value = result

    def get(self, timeout=None):
        return self._value

    def ready(self):
        return False

    def wait(self):
        return


class Windlass(object):

    def __init__(self,
                 products_to_parse=None,
                 artifacts=None,
                 workspace=None,
                 pool_size=4):
        if artifacts is not None:
            self.artifacts = artifacts
        else:
            self.artifacts = Artifacts(products_to_parse, workspace)
        self.max_retries = 3
        self.retry_backoff = 5

        self.pool_size = pool_size

        self._running = False
        self._pool = None
        self._failed = False

    def _er_cb(self, result):
        # Runs in same process as the run method, but not the main thread
        logging.error("Error callback called processing artifacts")
        self._failed = True
        self._pool.terminate()
        self._running = False
        # This is an error, so raise this method. This won't kill the
        # process as this is not in the main thread and is ignored.
        raise result

    def run(self, processor, type=None, parallel=True, **kwargs):
        if self._running:
            raise Exception('Windlass is already processing these artifacts')

        d = defaultdict(list)
        for artifact in self.artifacts:
            if type is not None and not isinstance(artifact, type):
                logging.debug(
                    'Skipping artifact %s because wrong type' % artifact.name)
                continue
            k = artifact.priority
            d[k].append(artifact)

        # Reset events.
        results = []

        self._failed = False
        self._pool = multiprocessing.Pool(self.pool_size)
        for i in reversed(sorted(d.keys())):
            for artifact in d[i]:
                if parallel:
                    result = self._pool.apply_async(
                        processor,
                        args=(
                            artifact,
                        ),
                        kwds=kwargs,
                        error_callback=self._er_cb)
                    self._running = True
                else:
                    # Call processor and wrap the result in a
                    # dummy result object
                    result = DummyResult(
                        processor(artifact, **kwargs)
                    )

                result.artifact = artifact
                results.append(result)

            # _pool.join will not abort running jobs
            def finished():
                return len([r for r in results if not r.ready()]) == 0

            # Wait for the current priority artifacts to be processed
            while self._running and not self._failed and not finished():
                for result in results:
                    if not result.ready():
                        result.wait(.2)

            # The error callback was called. This set _running to False
            # and terminated the pool of processes.
            if self._failed:
                raise Exception('Failed to process artifacts')

        # Allow future calls to run on the same set of artifacts to work
        self._running = False

        retd = {}
        for result in results:
            retd[result.artifact.name] = result.get()

        return [retd.get(a.name) for a in self.artifacts]

    def set_version(self, version):
        for artifact in self.artifacts:
            artifact.set_version(version)

    def list(self, version=None, type=None, **kwargs):
        list_items = []
        for artifact in self.artifacts:
            if type is None or isinstance(artifact, type):
                list_items.append(artifact.url(version, **kwargs))

        return list_items

    def build(self, parallel=True, **kwargs):
        self.run(_build_artifact, parallel=parallel)

    def download(self, version=None, type=None, parallel=True, **kwargs):
        """Download the artifact

        type - restrict to just downloading artifacts of this type

        version - override the version of the artifacts
        """
        return self.run(
            _download_artifact,
            type=type,
            parallel=parallel,
            **kwargs)

    def upload(self, version=None, type=None, parallel=True, **kwargs):
        """Upload artifact

        kwargs keywords contains the destination configuration. This
        is specific to the artifacts and registry we are uploading to.

        type - restrict to just uploading artifacts of this type

        version - override the version of the artifacts
        """
        return self.run(
            _upload_artifact,
            type=type,
            parallel=parallel,
            version=version,
            **kwargs)


def _build_artifact(artifact):
    return artifact.build()


def _download_artifact(artifact, version=None, **kwargs):
    return artifact.download(version=version, **kwargs)


def _upload_artifact(artifact, version=None, **kwargs):
    return artifact.upload(version=version, **kwargs)


def download(artifacts, parallel=True, **kwargs):
    g = Windlass(artifacts=artifacts)
    return g.download(parallel=parallel, **kwargs)


def upload(artifacts, parallel=True, **kwargs):
    g = Windlass(artifacts=artifacts)
    return g.upload(parallel=parallel, **kwargs)


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
        cls._type_str = self.key
        return cls
