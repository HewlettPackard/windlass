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

import windlass.charts
import windlass.images
import windlass.pins
import testtools


class TestImagePins(testtools.TestCase):

    def test_read_pins(self):
        artifacts = windlass.pins.read_pins('tests/integrationrepo')
        self.assertEqual(len(artifacts), 5)
        pins = {}
        artifact_types = {}
        for artifact in artifacts:
            # self.assertIsInstance(artifact, windlass.images.Image)
            pins[artifact.name] = artifact.version
            artifact_types[artifact.name] = artifact
        # Images
        self.assertEqual(pins['some/image'], 12345)
        self.assertIsInstance(
            artifact_types['some/image'], windlass.images.Image)
        self.assertEqual(pins['other/image'], 54321)
        self.assertIsInstance(
            artifact_types['other/image'], windlass.images.Image)
        self.assertEqual(pins['some/image2'], 12345)
        self.assertIsInstance(
            artifact_types['some/image2'], windlass.images.Image)
        self.assertEqual(pins['other/image2'], 54321)
        self.assertIsInstance(
            artifact_types['other/image2'], windlass.images.Image)

        # Charts
        self.assertEqual(pins['example1'], '0.0.1')
        self.assertIsInstance(artifact_types['example1'], windlass.charts.Chart)
