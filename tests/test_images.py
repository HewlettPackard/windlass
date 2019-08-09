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

import tarfile
import tempfile

import docker
import testtools

import windlass.images


class TestImageAPI(testtools.TestCase):

    def setUp(self):

        super().setUp()

        client = docker.from_env(version='auto')
        try:
            client.images.pull('alpine:3.5')
        finally:
            client.close()

    def test_missing_artifact(self):
        im = windlass.images.Image(dict(
            name='not_existing'
        ))
        e = self.assertRaises(
            windlass.exc.MissingArtifact,
            im.upload,
            docker_image_registry='127.0.0.1:23')
        self.assertEqual(e.artifact_name, 'not_existing')
        self.assertIsNotNone(e.errors)

    def test_export(self):
        im = windlass.images.Image(dict(
            name='alpine',
            version='3.5'
            ))

        with tempfile.TemporaryDirectory() as tmpdir:
            im.export(export_dir=tmpdir)

    def test_export_stream(self):
        im = windlass.images.Image(dict(
            name='alpine',
            version='3.5'
            ))

        with tempfile.NamedTemporaryFile() as tmpfile:
            stream = im.export_stream()
            try:
                for chunk in stream:
                    tmpfile.write(chunk)
            finally:
                stream.close()
            tmpfile.flush()

            # tmpfile is a container image
            with tarfile.open(tmpfile.name, 'r') as tf:
                members = [m.name for m in tf.getmembers()]
            self.assertThat(
                members, testtools.matchers.Contains('manifest.json'))
