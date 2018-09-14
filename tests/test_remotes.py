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
import botocore.stub
import windlass.remotes
import testtools

aws_region = 'test-region'
aws_account = '012345678901'


class TestECRConnector(testtools.TestCase):
    def setUp(self):
        super().setUp()
        tc = boto3.client(
            'ecr', aws_access_key_id='None', aws_secret_access_key='None',
            region_name='None',
        )
        self.stubber = botocore.stub.Stubber(tc)
        self.stubber.activate()

        auth_resp = {'authorizationData': [{
            'proxyEndpoint': 'https://%s.dkr.ecr.%s.amazonaws.com' % (
                aws_account, aws_region
            ),
            'authorizationToken': base64.b64encode(
                b'test_username:test_password'
            ).decode('utf-8'),
        }]}
        policy_stub = '{ "Statement": [{"Sid": "zing"}]}'
        self.stubber.add_response('get_authorization_token', auth_resp, {})

        self.connector = windlass.remotes.ECRConnector(
            creds=None, repo_policy=policy_stub, ecrc=tc,
        )
        # Set the retry backoff time to 0 to speed up tests.
        windlass.remotes.global_retry_backoff = 0

    # Stub helper functions for various ecr operations.
    def _stub_create_repository(self, image_name):
        self.stubber.add_response(
            'describe_repositories', {'repositories': []}, {}
        )
        inp = {'repositoryName': image_name}
        resp = {'repository': {
            'registryId': aws_account,
            'repositoryArn': 'arn:aws:ecr:%s:%s:repository/%s' % (
                aws_account, aws_region, image_name
            ),
            'repositoryUri': '%s.dkr.ecr.%s.amazonaws.com/%s' % (
                aws_account, aws_region, image_name
            ),
            'repositoryName': image_name,
        }}
        self.stubber.add_response('create_repository', resp, inp)

    def _stub_set_repository_policy(self, image_name):
        inp = {'repositoryName': image_name, 'policyText': botocore.stub.ANY}
        resp = {}  # Return value not used.
        self.stubber.add_response('set_repository_policy', resp, inp)

    def test_new_repo_create(self):
        image_name = 'my/new/image'

        self._stub_create_repository(image_name)
        self._stub_set_repository_policy(image_name)

        self.connector._create_repo_if_new(image_name)
        assert self.connector.existing_repos == set([image_name])

    def test_retry_on_fail(self):
        image_name = 'my/new/image'

        # First try - repo create appears to succeed (but repository not
        # created - perhaps still in progress), and set policy fails.
        self._stub_create_repository(image_name)
        self.stubber.add_client_error(
            'set_repository_policy', 'RepositoryNotFoundException'
        )
        # Second try - repo create now fails (repository already exists),
        # but set policy succeeds.
        self.stubber.add_client_error(
            'create_repository', 'RepositoryAlreadyExistsException'
        )
        self._stub_set_repository_policy(image_name)

        with self.assertLogs() as cmlogs:
            self.connector._create_repo_if_new(image_name)
            for logrecord in cmlogs.records:
                self.assertNotIn('Traceback', logrecord.msg)
        assert self.connector.existing_repos == set([image_name])

    def test_multiple_fail(self):
        image_name = 'my/new/image'

        # Three tries should fail and cause exceptions to be logged
        self._stub_create_repository(image_name)
        self.stubber.add_client_error(
            'set_repository_policy', 'RepositoryNotFoundException'
        )
        self.stubber.add_client_error(
            'create_repository', 'RepositoryNotFoundException'
        )
        self.stubber.add_client_error(
            'create_repository', 'RepositoryNotFoundException'
        )

        self._stub_set_repository_policy(image_name)

        with self.assertLogs() as cmlogs:
            e = self.assertRaises(
                Exception,
                self.connector._create_repo_if_new,
                image_name

            )  # noqa
            # Ensure three tracebacks are there
            tbs = 0
            for logrecord in cmlogs.records:
                if 'Traceback' in logrecord.msg:
                    tbs += 1
            self.assertEqual(tbs, 3)
            self.assertIn('Maximum number of retries occurred (3)', str(e))
