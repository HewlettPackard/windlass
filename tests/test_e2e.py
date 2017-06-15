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

import docker
import windlass
import os
from requests import get
import test.support
import testtools
from testtools.matchers import Equals


class Test_E2E(testtools.TestCase):

    def setUp(self):
        super().setUp()
        self.registry_port = test.support.find_unused_port()
        self.client = docker.from_env(version='auto')
        self.registry = self.client.containers.run(
            'registry:2',
            detach=True,
            ports={'5000/tcp': self.registry_port})

    def tearDown(self):
        super().tearDown()
        self.registry.kill()
        self.registry.remove()

    def test_tags_in_registry(self):
        base = os.path.dirname(os.path.dirname(__file__))
        # This uses the zing/windlass:latest image build during the tox -ebuild
        # step in ci/check.sh
        # This aslo rebuilds the image, we should only do this once and use
        # it to build and test other images.
        self.client.containers.run(
            'zing/windlass:latest',
            '--debug --directory %s --repository 127.0.0.1:%d dev' % (
                base, self.registry_port,
                ),
            remove=True,
            volumes={'/var/run/docker.sock': {'bind': '/var/run/docker.sock'},
                     base: {'bind': base}},
            environment=windlass.load_proxy(),
            )

        response = get(
            'http://127.0.0.1:%d/v2/zing/windlass/tags/list' % (
                self.registry_port))
        self.assertThat(response.status_code, Equals(200))
        self.assertThat(response.json()['name'], Equals('zing/windlass'))
