#
# (c) Copyright 2018 Hewlett Packard Enterprise Development LP
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

"""
Test support code for modules that use windlass
"""
# @reviewers - better to have this separate like this, or mingled with the main
# modules (e.g. remotes.py)?

import base64
import contextlib
import logging

import botocore.stub

import windlass.remotes

log = logging.getLogger(__name__)


class FakeECRConnector(windlass.remotes.ECRConnector):
    """A subclass of ECRConnector to enable testing

    Use by replacing windlass.remotes.ECRConnector with this class.
    """
    def __init__(self, creds, path_prefixes=None, repo_policy=None):
        # Moving to a new behaviour which requires that AWS region be
        # specified for tests.
        # Add a transition hack to allow moving to new behaviour - if the
        # region is not already set, set it and issue a warning.
        if creds.region is None:
            log.warning(
                "FakeECRConnector: Setting AWS region to 'test-region'"
            )
            creds = windlass.remotes.AWSCreds(
                creds.key_id, creds.secret_key, 'test-region'
            )
        self._aws_urn = (
            '%s.dkr.ecr.%s.amazonaws.com' % ('012345678901', creds.region)
        )
        policy_stub = '{ "Statement": [{"Sid": "zing"}]}'
        super().__init__(
            creds, path_prefixes, repo_policy or policy_stub
        )

    def _init_stubber(self, client):
        stubber = botocore.stub.Stubber(client)
        stubber.activate()

        auth_resp = {'authorizationData': [{
            'proxyEndpoint': 'https://%s' % self._aws_urn,
            'authorizationToken': base64.b64encode(
                b'test_username:test_password'
            ).decode('utf-8'),
        }]}
        stubber.add_response('get_authorization_token', auth_resp, {})
        return stubber

    def get_ecrc(self):
        client = super().get_ecrc()
        self._init_stubber(client)
        return client

    def upload(self, local_name, upload_name=None, upload_tag=None):

        # TODO(desbonne): Refactor windlass.remotes.ECRConnector to separate
        # this ECRConnector.upload() code to its own func:
        local_image_name, local_image_tag = local_name.split(':')
        if upload_name is None:
            upload_name = local_image_name
        upload_path = self.path_prefixes[0] + upload_name

        upload_url = (
            '%s/%s:%s' % (
                self._aws_urn, upload_path, upload_tag or local_image_tag
            ))
        log.info('FakeECRConnector upload to %s', upload_url)
        return upload_url


class FakeS3Connector(windlass.remotes.S3Connector):
    def upload(self, upload_name, stream):
        return self._obj_url(upload_name)


class FakeAWSRemote(windlass.remotes.AWSRemote):

    def setup_docker(self, *args, **kwargs):
        save_ecrconnector_class = windlass.remotes.ECRConnector
        windlass.remotes.ECRConnector = FakeECRConnector
        super().setup_docker(*args, **kwargs)
        windlass.remotes.ECRConnector = save_ecrconnector_class

    def setup_charts(self, *args, **kwargs):
        save_s3connector_class = windlass.remotes.S3Connector
        windlass.remotes.S3Connector = FakeS3Connector
        super().setup_charts(*args, **kwargs)
        windlass.remotes.S3Connector = save_s3connector_class


@contextlib.contextmanager
def AWSRemote_stub():
    save_class = windlass.remotes.AWSRemote
    windlass.remotes.AWSRemote = FakeAWSRemote
    yield
    windlass.remotes.AWSRemote = save_class
