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

import fixtures
import testtools

import windlass.registries


class TestRegistries(testtools.TestCase):

    def test_from_url_aws_ecr(self):
        registry_url = "000000000000.dkr.ecr.us-west-1.amazonaws.com"
        registry = windlass.registries.from_url(registry_url)

        self.assertIsInstance(registry, windlass.registries.EcrDockerRegistry)

    def test_from_url_jfrog(self):
        registry_url = "example-org.jfrog.io"
        registry = windlass.registries.from_url(registry_url)

        self.assertIsInstance(
            registry, windlass.registries.JfrogDockerRegistry
        )

    def test_from_url_hub(self):
        registry_url = "registry.hub.docker.com"
        registry = windlass.registries.from_url(registry_url)

        self.assertIsInstance(registry, windlass.registries.DockerRegistry)

    def test_from_url_other(self):
        registry_url = "registry.quay.io"
        registry = windlass.registries.from_url(registry_url)

        self.assertIsInstance(registry, windlass.registries.DockerRegistry)


class TestDockerRegistry(testtools.TestCase):

    reg_url = "registry.hub.docker.com"

    def test_credentials_from_env(self):
        self.useFixture(fixtures.EnvironmentVariable('DOCKER_USER', 'my_user'))
        self.useFixture(
            fixtures.EnvironmentVariable('DOCKER_PASSWORD', 'my_password')
        )
        registry = windlass.registries.DockerRegistry(self.reg_url)

        self.assertEqual('my_user', registry.username)
        self.assertEqual('my_password', registry.password)

    def test_credentials_ignore_env_when_set(self):
        self.useFixture(fixtures.EnvironmentVariable('DOCKER_USER', 'my_user'))
        self.useFixture(
            fixtures.EnvironmentVariable('DOCKER_PASSWORD', 'my_password')
        )
        registry = windlass.registries.DockerRegistry(
            self.reg_url,
            "explicit_user",
            "explicit_password",
        )

        self.assertEqual('explicit_user', registry.username)
        self.assertEqual('explicit_password', registry.password)


class TestEcrRegistry(testtools.TestCase):

    reg_url = "000000000000.dkr.ecr.us-west-1.amazonaws.com"

    def setUp(self):
        super().setUp()

        self.ecr_connector_mock = self.useFixture(
            fixtures.MockPatch('windlass.registries.remotes.ECRConnector')
        ).mock

    def test_credentials_from_env(self):
        self.useFixture(fixtures.EnvironmentVariable(
            'AWS_ACCESS_KEY_ID', 'AKIAIOSFODNN7EXAMPLE'))
        self.useFixture(fixtures.EnvironmentVariable(
            'AWS_SECRET_ACCESS_KEY', 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
            ))
        self.useFixture(fixtures.EnvironmentVariable(
            'AWS_DEFAULT_REGION', 'us-west-2'))

        registry = windlass.registries.EcrDockerRegistry(self.reg_url)

        self.assertIsNone(registry.username)
        self.assertIsNone(registry.password)
        call_args = self.ecr_connector_mock.call_args_list
        # check that ECRConnector class is called with AWSCreds containing
        # the example account key id as the first arg
        self.assertEqual(call_args[0][0][0][0], 'AKIAIOSFODNN7EXAMPLE')
        self.assertEqual(call_args[0][0][0][2], 'us-west-2')

    def test_credentials_default_region_from_url(self):
        self.useFixture(fixtures.EnvironmentVariable(
            'AWS_ACCESS_KEY_ID', 'AKIAIOSFODNN7EXAMPLE'))
        self.useFixture(fixtures.EnvironmentVariable(
            'AWS_SECRET_ACCESS_KEY', 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
            ))

        registry = windlass.registries.EcrDockerRegistry(self.reg_url)

        self.assertIsNone(registry.username)
        self.assertIsNone(registry.password)
        call_args = self.ecr_connector_mock.call_args_list
        # check that ECRConnector class is called with AWSCreds containing
        # the extracted region from the url
        self.assertEqual(call_args[0][0][0][2], 'us-west-1')

    def test_credentials_fallback_to_docker(self):
        self.useFixture(fixtures.EnvironmentVariable(
            'AWS_SECRET_ACCESS_KEY', ''))
        self.useFixture(fixtures.EnvironmentVariable(
            'DOCKER_USER', 'my_user'))
        self.useFixture(fixtures.EnvironmentVariable(
            'DOCKER_PASSWORD', 'my_password'))

        registry = windlass.registries.EcrDockerRegistry(self.reg_url)

        self.assertEqual('my_user', registry.username)
        self.assertEqual('my_password', registry.password)


class TestJfrogRegistry(testtools.TestCase):

    reg_url = "example-org.jfrog.io"

    def test_credentials_from_env(self):
        self.useFixture(fixtures.EnvironmentVariable(
            'ARTIFACTORY_USER', 'my_jfrog_user'))
        self.useFixture(fixtures.EnvironmentVariable(
            'ARTIFACTORY_PASSWORD', 'my_jfrog_password'))

        registry = windlass.registries.JfrogDockerRegistry(self.reg_url)

        self.assertEqual('my_jfrog_user', registry.username)
        self.assertEqual('my_jfrog_password', registry.password)

    def test_credentials_ignore_env_when_set(self):
        self.useFixture(fixtures.EnvironmentVariable(
            'ARTIFACTORY_USER', 'my_jfrog_user'))
        self.useFixture(fixtures.EnvironmentVariable(
            'ARTIFACTORY_PASSWORD', 'my_jfrog_password'))

        registry = windlass.registries.JfrogDockerRegistry(
            self.reg_url,
            "explicit_user",
            "explicit_password",
        )

        self.assertEqual('explicit_user', registry.username)
        self.assertEqual('explicit_password', registry.password)

    def test_credentials_from_env_api_key_when_set(self):
        self.useFixture(fixtures.EnvironmentVariable(
            'ARTIFACTORY_USER', 'my_jfrog_user'))
        self.useFixture(fixtures.EnvironmentVariable(
            'ARTIFACTORY_API_KEY', 'my_jfrog_token'))

        registry = windlass.registries.JfrogDockerRegistry(self.reg_url,)

        self.assertEqual('my_jfrog_user', registry.username)
        self.assertEqual('my_jfrog_token', registry.password)
