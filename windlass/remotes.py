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
import base64
import boto3
import docker
import logging
import os
import urllib.parse

import windlass.api
import windlass.images


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

    @windlass.api.retry()
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
    def __init__(self, key_id, secret_key, region,
                 path_prefixes=None, repo_policy=None):
        self.key_id = key_id
        self.secret_key = secret_key
        self.region = region
        if path_prefixes is None:
            self.path_prefixes = ['']
        elif not isinstance(path_prefixes, list):
            self.path_prefixes = [path_prefixes]
        else:
            self.path_prefixes = path_prefixes
        self.new_repo_policy = repo_policy
        self.ecrc = boto3.client(
            'ecr', aws_access_key_id=self.key_id,
            aws_secret_access_key=self.secret_key, region_name=self.region,
        )
        self.existing_repos = self._list_existing_repos()
        reg, user, passwd = self._docker_login()
        super().__init__([reg], user, passwd)

    def _docker_login(self):
        """Get a docker login for the ECR registry

        Returns a <registry>, <username>, <password> 3-tuple.
        """
        resp = self.ecrc.get_authorization_token()
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

    def _create_repo_if_new(self, image_name):
        if image_name not in self.existing_repos:
            logging.info("Creating new repository: %s", image_name)
            self.ecrc.create_repository(repositoryName=image_name)
            self.existing_repos.add(image_name)
            self._set_repo_policy(image_name)

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


class AWSRemote(windlass.api.Remote):
    """Encapsulate access to AWS repositories"""
    def __init__(self, key_id=None, secret_key=None, region=None):
        self.key_id = key_id or os.environ['AWS_ACCESS_KEY_ID']
        self.secret_key = secret_key or os.environ['AWS_SECRET_ACCESS_KEY']
        self.region = region or os.environ.get('AWS_DEFAULT_REGION')
        self.ecr = None

    def __str__(self):
        return "AWSRemote(region=%s, key_id=%s)" % (self.region, self.key_id)

    def setup_docker(self, path_prefixes=None, repo_policy=None):
        self.ecr = ECRConnector(
            self.key_id, self.secret_key, self.region,
            path_prefixes, repo_policy,
        )

    def upload_docker(self, local_name, upload_name=None, upload_tag=None):
        if self.ecr is None:
            raise windlass.api.NoValidRemoteError(
                'Docker not configured for %s' % self
            )
        return self.ecr.upload(local_name, upload_name, upload_tag)

    def get_docker_upload_registry(self):
        if self.ecr is None:
            raise windlass.api.NoValidRemoteError(
                'Docker not configured for %s' % self
            )
        return self.ecr.registry_list[0]
