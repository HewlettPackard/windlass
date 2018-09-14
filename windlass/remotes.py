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
import base64
import boto3
import botocore.exceptions
import collections
import docker
import functools
import logging
import os
import requests
import time
import traceback
import urllib.parse

import windlass.api
import windlass.exc
import windlass.images


# Define an AWSCreds lightweight class, which also includes the region to use
AWSCreds = collections.namedtuple(
    'AWSCreds', ['key_id', 'secret_key', 'region']
)

# Set retry_backoff as a module-level variable to allow override for tests.
global_retry_backoff = 5


class remote_retry(object):
    """Retry decorator for AWS operations

    Accepts an exceptions list of exception classes to retry on, in addition
    to the hard-coded ones.
    """

    def __init__(self, max_retries=3, retry_backoff=None, retry_on=None):
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff or global_retry_backoff
        # Set the exceptions to retry on - initialise with a hard-coded
        # list and add custom ones.
        self.retry_on = set([windlass.exc.RetryableFailure])
        if retry_on:
            self.retry_on.update(retry_on)
        self._raised = []

    def __call__(self, func):
        @functools.wraps(func)
        def retry_f(*args, **kwargs):
            for i in range(0, self.max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if not any(isinstance(e, r) for r in self.retry_on):
                        raise
                    self._raised.append(traceback.format_exc())
                    logging.info(
                        '%s: problem occuried retrying, backing '
                        'off %d seconds' % (
                            func, self.retry_backoff))
                    time.sleep(self.retry_backoff)

            logging.error('Attempted %d times with following results:'
                          % self.max_retries)
            for no, tb in enumerate(self._raised):
                logging.error('Attempt %d' % (no + 1))
                logging.error(tb)
            raise Exception('%s: Maximum number of retries occurred (%d)' % (
                func, self.max_retries))

        return retry_f


class DockerConnector(object):
    """Interface with a remote docker registry.

    Supports multiple registries for download, with each being tried in turn
    until a requested image is found.

    Upload is always to the first registry.
    """
    def __init__(self, registry_list, username, password):
        self.username = username
        self.password = password
        if not isinstance(registry_list, list):
            self.registry_list = [registry_list]
        else:
            self.registry_list = registry_list

    @remote_retry()
    def upload(self, local_name, upload_name=None, upload_tag=None):
        dcli = docker.from_env(version='auto')
        auth_config = {'username': self.username, 'password': self.password}
        local_image_name, local_image_tag = local_name.split(':')
        if upload_name is None:
            upload_name = local_image_name
        if upload_tag is None:
            upload_tag = local_image_tag
        upload_path = '%s/%s' % (self.registry_list[0], upload_name)
        upload_url = '%s:%s' % (upload_path, upload_tag)
        try:
            dcli.api.tag(local_name, upload_path, upload_tag)

            logging.info('%s: Pushing as %s', local_name, upload_url)
            output = dcli.images.push(
                upload_path, upload_tag, auth_config=auth_config, stream=True
            )
            windlass.images.check_docker_stream(output)
            return upload_url
        finally:
            dcli.api.remove_image(upload_url)

    def download_docker(self, image_name):
        pass


class ECRConnector(DockerConnector):
    """Interface with an ECR registry

    Supports multiple paths for download within the single registry.

    Upload is always to the first path, if specified.
    """
    def __init__(self, creds, path_prefixes=None, repo_policy=None,
                 ecrc=None):
        self.creds = creds
        if path_prefixes is None:
            self.path_prefixes = ['']
        elif not isinstance(path_prefixes, list):
            self.path_prefixes = [path_prefixes]
        else:
            self.path_prefixes = path_prefixes
        self.new_repo_policy = repo_policy
        # Allow for specifying a test ECR client, for running tests.
        self._ecrc = ecrc

        self._existing_repos = None

        reg, user, passwd = self._docker_login()
        super().__init__([reg], user, passwd)

    def get_ecrc(self):
        return boto3.client(
            'ecr', aws_access_key_id=self.creds.key_id,
            aws_secret_access_key=self.creds.secret_key,
            region_name=self.creds.region,
        )

    @property
    def ecrc(self):
        if not self._ecrc:
            self._ecrc = self.get_ecrc()
        return self._ecrc

    # Retry on ClientError exception.
    # Specifically with a 'UnrecognizedClientException' but this does not
    # seem to be determinable except by examining the exception message.
    # This happens for a key_id that does not (yet) exist - e.g. just after
    # vault creates an ephemeral credentials.  Longer backoff than usual to
    # give AWS more time.
    @remote_retry(retry_on=[botocore.exceptions.ClientError], max_retries=5, retry_backoff=30)  # noqa
    def _docker_login(self):
        """Get a docker login for the ECR registry

        Returns a <registry>, <username>, <password> 3-tuple.
        """
        # Since _docker_login is called in __init__ we can't access
        # the self.ecrc property here as it will persist the ECR client
        # on this object making it non-pickleable
        resp = (self._ecrc or self.get_ecrc()).get_authorization_token()
        docker_reg_url = resp['authorizationData'][0]['proxyEndpoint']
        registry = urllib.parse.urlparse(docker_reg_url)[1]
        up = base64.b64decode(
            resp['authorizationData'][0]['authorizationToken']
        ).decode("utf-8")
        username, password = up.split(':', 1)
        logging.info("AWS Docker token obtained for registry %s", registry)
        return registry, username, password

    def _list_existing_repos(self):
        paginator = self.ecrc.get_paginator('describe_repositories')
        existing_repos = set()
        for page in paginator.paginate():
            existing_repos.update(
                set(r['repositoryName'] for r in page['repositories'])
            )
        return existing_repos

    @property
    def existing_repos(self):
        if self._existing_repos is None:
            self._existing_repos = self._list_existing_repos()

        return self._existing_repos

    def _create_repo_if_new(self, image_name):
        if image_name in self.existing_repos:
            return

        # The retry exception is defined within the client so declaring this
        # embedded function in order to be able to wrap it.
        @remote_retry(retry_on=[self.ecrc.exceptions.RepositoryNotFoundException])  # noqa
        def _create_repo():
            logging.info("Creating new repository: %s", image_name)
            try:
                ret = self.ecrc.create_repository(repositoryName=image_name)
                logging.info(
                    "New repository uri: %s",
                    ret['repository']['repositoryUri']
                )
            except self.ecrc.exceptions.RepositoryAlreadyExistsException:
                logging.info("Repository %s already exists", image_name)
            self._set_repo_policy(image_name)

        _create_repo()
        self.existing_repos.add(image_name)

    def _set_repo_policy(self, repository_name):
        if self.new_repo_policy:
            policy_text = self.new_repo_policy
            self.ecrc.set_repository_policy(
                repositoryName=repository_name, policyText=policy_text
            )

    def upload(self, local_name, upload_name=None, upload_tag=None):
        local_image_name, local_image_tag = local_name.split(':')
        if upload_name is None:
            upload_name = local_image_name
        upload_path = self.path_prefixes[0] + upload_name

        self._create_repo_if_new(upload_path)
        return super().upload(local_name, upload_path, upload_tag)


class S3Connector(object):
    def __init__(self, creds, bucket, path_prefix=None):
        self.creds = creds
        self.bucket = bucket
        self.path_prefix = path_prefix or ''
        self._s3c = None

    def _obj_url(self, upload_name):
        return 'https://%s.s3.amazonaws.com/%s%s' % (
            self.bucket, self.path_prefix, upload_name
        )

    @property
    def s3c(self):
        if not self._s3c:
            key_id, secret_key, region = self.creds
            self._s3c = boto3.client(
                's3',
                region_name=region,
                aws_access_key_id=key_id,
                aws_secret_access_key=secret_key,
            )
        return self._s3c

    def upload(self, upload_name, stream):
        key = self.path_prefix + upload_name
        logging.info("Upload to s3://%s/%s", self.bucket, key)
        self.s3c.upload_fileobj(stream, self.bucket, key)
        return self._obj_url(upload_name)


class HTTPBasicAuthConnector(object):
    def __init__(self, url, username, password):
        self.base_url = url
        self.username = username
        self.password = password

    def upload(self, upload_name, stream, properties={}):
        auth = requests.auth.HTTPBasicAuth(
            self.username, self.password
        )

        upload_url = os.path.join(self.base_url, upload_name)
        logging.info("Upload to %s" % upload_url)

        props = ';'.join(['%s=%s' % (k, v) for k, v in properties.items()])
        if props:
            upload_url = '%s;%s' % (upload_url, props)
        resp = requests.put(
            upload_url,
            data=stream,
            auth=auth,
            verify='/etc/ssl/certs')
        if resp.status_code in (
                requests.codes.unauthorized, requests.codes.forbidden):
            # No retries in this case.
            raise Exception('Permission error (%s) uploading generic %s' % (
                resp, upload_url))
        if resp.status_code != 201:
            raise windlass.exc.RetryableFailure(
                'Failed (status: %d) to upload %s' % (
                    resp.status_code, upload_url))
        return upload_url


class HTTPBasicAuthConnector2Phase(HTTPBasicAuthConnector):
    """Simple connector to publish artifacts over http

    temp_path: If the temp_path is set then the system windlass
    is embedded in is performing a two step transaction. First
    push up the artiact under the temp_path, and the then later
    move this artifact to its final location.

    If the temp_path is set then we will check if the artifact
    exists in the final location. If it does we will raise an
    exception.
    """

    def __init__(self, url, username, password, temp_path=''):
        super().__init__(url, username, password)
        self.temp_path = temp_path

    def upload(self, upload_name, stream, properties={}):
        if self.temp_path:
            # Don't upload the artifact if the artifact exists in the
            # final location.
            # TODO(kerrin) make this configurable
            check_url = os.path.join(self.base_url, upload_name)
            check_resp = requests.head(check_url, verify='/etc/ssl/certs')
            if check_resp.ok:
                raise Exception('Artifact %s already exists' % check_url)

        return super().upload(
            os.path.join(self.temp_path, upload_name),
            stream,
            properties=properties)


class AWSRemote(windlass.api.Remote):
    """Encapsulate access to AWS repositories"""
    def __init__(self, key_id=None, secret_key=None, region=None):
        self.creds = AWSCreds(
            key_id or os.environ['AWS_ACCESS_KEY_ID'],
            secret_key or os.environ['AWS_SECRET_ACCESS_KEY'],
            region or os.environ.get('AWS_DEFAULT_REGION'),
        )
        self.ecr = None
        self.signature_connector = None
        self.generic_connector = None
        self.charts_connector = None

    def __str__(self):
        return "AWSRemote(region=%s, key_id=%s)" % (
            self.creds.region, self.creds.key_id
        )

    def setup_docker(self, path_prefixes=None, repo_policy=None):
        self.ecr = ECRConnector(self.creds, path_prefixes, repo_policy)

    def upload_docker(self, local_name, upload_name=None, upload_tag=None):
        if self.ecr:
            return self.ecr.upload(local_name, upload_name, upload_tag)
        raise windlass.api.NoValidRemoteError(
            "No %s connector configured for docker" % self)

    def get_docker_upload_registry(self):
        return self.ecr.registry_list[0]

    def setup_signatures(self, bucket):
        self.signature_connector = S3Connector(self.creds, bucket)

    def upload_signature(self, artifact_type, sig_name, sig_stream):
        if self.signature_connector:
            path = artifact_type + '/' + sig_name
            return self.signature_connector.upload(path, sig_stream)
        raise windlass.api.NoValidRemoteError(
            "No %s connector configured for signatures" % self)

    def setup_generic(self, bucket, prefix=None):
        self.generic_connector = S3Connector(self.creds, bucket, prefix)

    def upload_generic(self, name, stream, properties={}):
        if self.generic_connector:
            # Ignore properties for AWS
            return self.generic_connector.upload(name, stream)
        raise windlass.api.NoValidRemoteError(
            "No %s connector configured for generics" % self)

    def setup_charts(self, bucket, prefix=None):
        self.charts_connector = S3Connector(self.creds, bucket, prefix)

    def upload_chart(self, name, stream, properties={}):
        if self.charts_connector:
            # Ignore properties for AWS
            return self.charts_connector.upload(name, stream)
        raise windlass.api.NoValidRemoteError(
            "No %s connector configured for charts" % self)


class ArtifactoryRemote(windlass.api.Remote):
    def __init__(self, username, password):
        self.username = username
        self.password = password
        # TODO(desbonne): Might make more sense to bring the connection
        # code directly into this class, but leaving external for the moment
        # (as HTTPBasicAuthConnector)
#        self.docker = None
        self.signature_connector = None
        self.generic_connector = None

    def upload_docker(self, local_name, upload_name=None, upload_tag=None):
        raise windlass.api.NoValidRemoteError("Not implemented")
#        return self.docker.upload(local_name, upload_name, upload_tag)

    def setup_signatures(self, url):
        self.signature_connector = HTTPBasicAuthConnector(
            url, self.username, self.password
        )

    def upload_signature(self, artifact_type, sig_name, sig_stream):
        if self.signature_connector:
            path = artifact_type + '/' + sig_name
            return self.signature_connector.upload(path, sig_stream)
        raise windlass.api.NoValidRemoteError(
            "No %s connector configured for signatures" % self)

    def setup_generic(self, url, temp_path):
        self.generic_connector = HTTPBasicAuthConnector2Phase(
            url, self.username, self.password, temp_path=temp_path,
        )

    def upload_generic(self, name, stream, properties):
        if self.generic_connector:
            return self.generic_connector.upload(
                name, stream, properties=properties)
        raise windlass.api.NoValidRemoteError(
            "No %s connector configured for generics" % self)

    # No setup_charts() method because charts are not supported here, but
    # implement a stub upload_chart() to allow fallthru to the upload
    # code in charts.Chart.upload()
    def upload_chart(self, name, stream, properties):
        raise windlass.api.NoValidRemoteError(
            "No %s connector configured for charts" % self
        )
