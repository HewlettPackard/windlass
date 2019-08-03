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
import pathlib
import unittest
import unittest.mock
import uuid

import windlass.exc
import windlass.images

import tests.test_e2e


class DockerImage(fixtures.Fixture):
    def __init__(self, imagename, dockerfileprefix=None):
        if dockerfileprefix:
            self.dockerfile = '%s.Dockerfile' % dockerfileprefix
        else:
            self.dockerfile = '%s.Dockerfile' % imagename
        self.imagename = imagename

    def _setUp(self):
        self.docker_client = docker.from_env(version='auto')
        self.addCleanup(self.docker_client.close)
        path = pathlib.Path(__file__).parent.as_posix()
        dockerpath = pathlib.Path(__file__).stem
        self.docker_client.images.build(
            path=path,
            dockerfile='%s/%s' % (dockerpath, self.dockerfile),
            tag=self.imagename)
        # Cleanup will be added after successful building of image, as
        # otherwise image delete would fail.
        self.addCleanup(self.docker_client.images.remove, self.imagename)


class TestDockerUtils(tests.test_e2e.FakeRegistry):

    def setUp(self):
        super().setUp()
        self.random_name = 'test_%s' % uuid.uuid4().hex
        self.logger = self.useFixture(fixtures.FakeLogger(level=logging.DEBUG))

    def cleanUp(self):
        super().cleanUp()
        with docker.from_env(version='auto', timeout=180) as client:
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
        e = self.assertRaises(
            windlass.exc.WindlassBuildException,
            windlass.images.build_verbosly,
            self.random_name,
            temp.path,
            dockerfile='Dockerfile')

        self.assertIsNotNone(e.out)
        self.assertIsNotNone(e.errors)
        self.assertIsNotNone(e.artifact_name)
        self.assertIsNotNone(e.debug_data)
        debug_output = e.debug_message()
        for line in e.out + e.errors:
            self.assertIn(line, debug_output)

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

    def test_failed_push_image(self):
        imname = '127.0.0.1:23/%s' % self.random_name
        self.useFixture(
            DockerImage(imname, 'simple')
        )
        e = self.assertRaises(
            windlass.exc.WindlassPushPullException,
            windlass.images.push_image,
            imname)
        self.assertIsNotNone(e.out)
        self.assertIsNotNone(e.errors)
        debug_output = e.debug_message()
        for line in e.out + e.errors:
            self.assertIn(line, debug_output)
        # Exception is currently raised in piece of code where this info is
        # not avaliable, as it is function parsing stream output from docker.
        # This will be chaned in future.
        # self.assertIsNotNone(e.artifact_name)
        # self.assertIsNotNone(e.debug_data)

    def test_retry_push_image(self):
        imname = '127.0.0.1:23/%s' % self.random_name
        self.useFixture(
            DockerImage(imname, 'simple')
        )

        @windlass.retry.simple(retry_backoff=0.1)
        def artifact_pushing_func(artifact):
            windlass.images.push_image(imname)
        mock_artifact = unittest.mock.MagicMock()
        mock_artifact.name = 'ArtifactName'

        e = self.assertRaises(
            windlass.exc.FailedRetriesException,
            artifact_pushing_func,
            mock_artifact
        )
        self.assertEqual(len(e.attempts), 3)
        self.assertIsInstance(
            e.attempts[0], windlass.exc.WindlassPushPullException
        )

    def test_push_image(self):
        imname = '127.0.0.1:%d/%s' % (
            self.registry_port,
            self.random_name)
        self.useFixture(
            DockerImage(imname, 'simple'))
        windlass.images.push_image(imname)

    def test_build_with_buildargs(self):
        temp = self.useFixture(
            fixtures.TempDir()
        )
        self.useFixture(
            fixtures.EnvironmentVariable(
                'WINDLASS_BUILDARG_ARGUMENT',
                'somevalue'
            )
        )
        with open('%s/Dockerfile' % temp.path, 'w') as f:
            f.write(
                'FROM alpine\n'
                'ARG ARGUMENT\n'
                'RUN echo -n $ARGUMENT > content.txt\n'
                'CMD cat content.txt'
            )
        im = windlass.images.build_verbosly(
            self.random_name,
            temp.path,
            dockerfile='Dockerfile')
        client = docker.from_env(
            version='auto',
            timeout=180)

        try:
            # To capture all output to inspect, must delay removal until
            # after retrieval of logs otherwise the API can sometimes return
            # an empty result
            c = client.containers.create(im)
            c.start()
            result = c.wait()
            output = c.logs(stdout=True, stderr=True)
        finally:
            c.stop()
            c.remove()
            client.close()
        # make sure completed successfully
        self.assertEqual(0, result['StatusCode'])
        self.assertEqual('somevalue', output.decode())
