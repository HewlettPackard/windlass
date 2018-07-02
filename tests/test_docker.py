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

import docker
import fixtures
import logging
import testtools
import uuid

import windlass.exc
import windlass.images


class TestDockerUtils(testtools.TestCase):

    def setUp(self):
        super().setUp()
        self.random_name = 'test_%s' % uuid.uuid4().hex
        self.logger = self.useFixture(fixtures.FakeLogger(level=logging.DEBUG))

    def cleanUp(self):
        super().cleanUp()
        client = docker.from_env(
            version='auto',
            timeout=180)
        try:
            client.api.remove_image(self.random_name)
        except docker.errors.ImageNotFound:
            # Image isn't on system so no worries
            pass

    def test_failed_image_build(self):
        temp = self.useFixture(
            fixtures.TempDir()
        )
        with open('%s/Dockerfile' % temp.path, 'w') as f:
            f.write(
                'FROM alpine\n'
                'RUN exit 1\n'

            )
        with testtools.ExpectedException(windlass.exc.WindlassBuildException):
            windlass.images.build_verbosly(
                self.random_name,
                temp.path,
                dockerfile='Dockerfile')

    def test_image_build_delete(self):
        temp = self.useFixture(
            fixtures.TempDir()
        )
        with open('%s/Dockerfile' % temp.path, 'w') as f:
            f.write(
                'FROM alpine\n'
                'RUN exit 0\n'
            )
        windlass.images.build_verbosly(
            self.random_name,
            temp.path,
            dockerfile='Dockerfile')
