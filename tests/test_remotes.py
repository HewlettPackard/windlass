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
import unittest

import boto3
import botocore.stub
import testtools

import windlass.remotes

aws_region = 'test-region'
aws_account = '012345678901'
aws_key_id = 'AKIA000TESTKEYID0000'
aws_secret_key = 'VUoSL+TestSecretKey+P8JPAuL2a/0doizdNHxc'
# Define some stock policies
ecr_access_policies = [
    '{ "Statement": [{"Sid": "zing1"}]}',
    '{ "Statement": [{"Sid": "zing2"}]}',
]
ecr_lifecycle_policies = [
    '{ "rules": [] }',
]


class TestECRConnectorBase(testtools.TestCase):
    def setUp(self):
        super().setUp()
        self.ecr_client = boto3.client(
            'ecr', aws_access_key_id='None', aws_secret_access_key='None',
            region_name='None',
        )
        self.stubber = botocore.stub.Stubber(self.ecr_client)
        self.stubber.activate()

        auth_resp = {'authorizationData': [{
            'proxyEndpoint': 'https://%s.dkr.ecr.%s.amazonaws.com' % (
                aws_account, aws_region
            ),
            'authorizationToken': base64.b64encode(
                b'test_username:test_password'
            ).decode('utf-8'),
        }]}
        self.stubber.add_response('get_authorization_token', auth_resp, {})

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

    def _stub_put_lifecycle_policy(self, image_name):
        inp = {
            'repositoryName': image_name,
            'lifecyclePolicyText': botocore.stub.ANY
        }
        resp = {}  # Return value not used.
        self.stubber.add_response('set_repository_policy', resp, inp)


class TestECRConnectorInitialisation(TestECRConnectorBase):
    """Test initialisation of ECRConnector objects."""

    def test_using_repo_policy(self):
        policy = ecr_access_policies[0]
        connector = windlass.remotes.ECRConnector(
            creds=None, repo_policy=policy, ecrc=self.ecr_client,
        )
        self.assertEqual(connector.new_repo_policy, policy)
        self.assertIsNone(connector.new_repo_lifecycle_policy)

    def test_using_repo_policies_as_string(self):
        policy = ecr_access_policies[1]
        connector = windlass.remotes.ECRConnector(
            creds=None, repo_policies=policy, ecrc=self.ecr_client,
        )
        self.assertEqual(connector.new_repo_policy, policy)
        self.assertIsNone(connector.new_repo_lifecycle_policy)
        pass

    def test_repo_policies_overrides_repo_policy(self):
        old_policy = ecr_access_policies[0]
        new_policy = {
          'access': ecr_access_policies[1],
          'lifecycle': ecr_lifecycle_policies[0],
        }
        connector = windlass.remotes.ECRConnector(
            creds=None, repo_policies=new_policy, repo_policy=old_policy,
            ecrc=self.ecr_client,
        )
        self.assertEqual(connector.new_repo_policy, new_policy['access'])
        self.assertEqual(
            connector.new_repo_lifecycle_policy, new_policy['lifecycle']
        )

    def test_positional_repo_policies_as_string(self):
        policy = ecr_access_policies[0]
        creds = None
        path_prefixes = None
        connector = windlass.remotes.ECRConnector(
            creds, path_prefixes, policy, ecrc=self.ecr_client
        )
        self.assertEqual(connector.new_repo_policy, policy)

    def test_positional_repo_policies_as_dict(self):
        policy = {
            'access': ecr_access_policies[0],
            'lifecycle': ecr_lifecycle_policies[0],
        }
        creds = None
        path_prefixes = None
        connector = windlass.remotes.ECRConnector(
            creds, path_prefixes, policy, ecrc=self.ecr_client
        )
        self.assertEqual(connector.new_repo_policy, policy['access'])
        self.assertEqual(
            connector.new_repo_lifecycle_policy, policy['lifecycle']
        )


class TestECRConnectorUsage(TestECRConnectorBase):
    def setUp(self):
        super().setUp()
        policies = {
            'access': '{ "Statement": [{"Sid": "zing"}]}',
            'lifecycle': None,
        }
        self.connector = windlass.remotes.ECRConnector(
            creds=None, repo_policies=policies, ecrc=self.ecr_client,
        )

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


class TestAWSRemote(TestECRConnectorBase):

    def setUp(self):
        super().setUp()
        self.remote = windlass.remotes.AWSRemote(
            aws_key_id, aws_secret_key, aws_region
        )
        # Apply a patch to the ECRConnector.get_ecrc() method to return the
        # stubbed boto3 client.
        boto_client_mock = unittest.mock.patch(
            'windlass.remotes.ECRConnector.get_ecrc'
        )
        self.addCleanup(boto_client_mock.stop)
        boto_client_mock.start().return_value = self.ecr_client

    def test_ecr_repo_policies_as_string(self):
        """Test that ECR policies are passed through to the ECRConnector"""
        path_prefixes = None
        self.remote.setup_docker(path_prefixes, ecr_access_policies[0])

        self.assertEqual(
            self.remote.ecr.new_repo_policy, ecr_access_policies[0]
        )
        self.assertIsNone(self.remote.ecr.new_repo_lifecycle_policy)

    def test_ecr_repo_policies_as_dict(self):
        """Test that ECR policies are passed through to the ECRConnector"""
        path_prefixes = None
        policy = {
            'access': ecr_access_policies[0],
            'lifecycle': ecr_lifecycle_policies[0],
        }
        self.remote.setup_docker(path_prefixes, policy)

        self.assertEqual(self.remote.ecr.new_repo_policy, policy['access'])
        self.assertEqual(
            self.remote.ecr.new_repo_lifecycle_policy, policy['lifecycle']
        )
