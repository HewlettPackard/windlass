#
# (c) Copyright 2019 Hewlett Packard Enterprise Development LP
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

import os
import re

from windlass import remotes

AWS_ECR_REGEX = r'''
    (?P<account_id>     # capture the account of the ECR
        [0-9]{12}
    )
    \.dkr\.ecr\.        # string used by ecr currently
    (?P<region>         # capture the region for the ECR
        [^\.]+
    )
    .amazonaws.com      # domain for all aws services
'''
JFROG_REGISTRY_REGEX = r"[^\.]+\.jfrog\.io"


def from_url(url, username=None, password=None):
    """Docker registry factory function

    To assist in auto determining the correct registry config object to
    use to back a registry config when passed on the command line or
    provided in a config file without explicit identification, this factory
    will inspect the url and attempt to make a guess at the correct
    """
    if re.match(AWS_ECR_REGEX, url, re.VERBOSE):
        return EcrDockerRegistry(url, username, password)
    elif re.match(JFROG_REGISTRY_REGEX, url):
        return JfrogDockerRegistry(url, username, password)
    else:
        return DockerRegistry(url, username, password)


class DockerRegistry(object):

    def __init__(self, url, username=None, password=None):
        self.url = url
        self.username = username
        self.password = password

        self.connector = self.get_connector()

    def get_connector(self):
        # retrieval from the env should move to a config object in future.
        if self.username is None:
            self.username = os.environ.get('DOCKER_USER')

        if self.password is None:
            self.password = os.environ.get('DOCKER_PASSWORD')

        return remotes.DockerConnector(
            self.url, self.username, self.password
        )

    def __str__(self):
        return self.url


class EcrDockerRegistry(DockerRegistry):

    def get_connector(self):
        # support loading auth based on AWS credentials in env
        if not os.environ.get('AWS_SECRET_ACCESS_KEY'):
            return super().get_connector()

        # retrieval from the env should move to a config object in future.
        matcher = re.match(AWS_ECR_REGEX, self.url, re.VERBOSE)
        key_id = os.environ.get('AWS_ACCESS_KEY_ID')
        secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
        region = os.environ.get('AWS_DEFAULT_REGION', matcher.group('region'))
        creds = remotes.AWSCreds(key_id, secret_key, region)
        return remotes.ECRConnector(creds)


class JfrogDockerRegistry(DockerRegistry):

    def get_connector(self):
        # support loading auth based on ARTIFACTORY creds in env

        # retrieval from the env should move to a config object in future.
        self.username = self.username or os.environ.get('ARTIFACTORY_USER')
        self.password = self.password or os.environ.get(
            'ARTIFACTORY_PASSWORD',
            os.environ.get('ARTIFACTORY_API_KEY')
        )

        return remotes.DockerConnector(
            self.url, self.username, self.password
        )
