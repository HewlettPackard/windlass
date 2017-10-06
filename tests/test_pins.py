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
import os.path
import shutil
import tempfile
import testtools
import yaml


class TestPins(testtools.TestCase):

    def setUp(self):
        super().setUp()
        self.tempdir = tempfile.TemporaryDirectory()
        # self.repodir = self.tempdir.name
        self.repodir = os.path.join(self.tempdir.name, 'integrationrepo')
        self.repodir_rhs = os.path.join(self.tempdir.name,
                                        'integrationrepo_rhs')
        shutil.copytree('./tests/integrationrepo', self.repodir)
        shutil.copytree('./tests/integrationrepo_rhs', self.repodir_rhs)

    def test_read_pins(self):
        artifacts = windlass.pins.read_pins(self.repodir)
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
        self.assertEqual(artifact_types['some/image2'].devtag, 2)
        self.assertEqual(pins['other/image2'], 54321)
        self.assertIsInstance(
            artifact_types['other/image2'], windlass.images.Image)
        self.assertEqual(artifact_types['other/image2'].devtag, 'latest')

        # Charts
        self.assertEqual(pins['example1'], '0.0.1')
        self.assertIsInstance(artifact_types['example1'], windlass.charts.Chart)

    def test_diff_pins(self):
        pins_lhs = windlass.pins.read_pins(self.repodir)
        pins_rhs = windlass.pins.read_pins(self.repodir_rhs)
        self.assertEqual(len(pins_lhs), 5)
        self.assertEqual(len(pins_rhs), 5)

        artifacts = windlass.pins.diff_pins_dir(self.repodir, self.repodir_rhs)

        # deletes
        n = [x['name'] for x in artifacts if x['lhs'] and not x['rhs']]
        self.assertEqual(n, ['other/image'])

        # adds
        n = [x['name'] for x in artifacts if x['rhs'] and not x['lhs']]
        self.assertEqual(n, ['some/newimage'])

        # updates
        n = [x for x in artifacts if x['rhs'] and x['lhs']]
        sorted_updates = sorted(n, key=lambda k: k['name'])

        self.assertEqual(sorted_updates[0]['name'], 'some/image')
        self.assertEqual(sorted_updates[0]['lhs'].version, 12345)
        self.assertEqual(sorted_updates[0]['rhs'].version, 12346)

    def test_write_chart_pins(self):
        artifacts = [
            windlass.charts.Chart(dict(
                name='example1')),
            windlass.charts.Chart(dict(
                name='example2')),
            windlass.charts.Chart(dict(
                name='example3')),
            ]
        updated_files = windlass.pins.write_pins(
            artifacts, '1.0.0', 'repo', self.repodir)
        self.assertEqual(updated_files, [
            'region1/example1.yaml',
            'region1/example2.yaml',
            'region1/example3.yaml',
            'region2/example1.yaml',
            'region2/example2.yaml',
            'region2/example3.yaml'])

        region1data1 = yaml.safe_load(
            open(os.path.join(self.repodir, 'region1', 'example1.yaml')))
        self.assertEqual(
            region1data1['release']['chart'], 'staging-charts/example1:1.0.0')
        self.assertEqual(region1data1['release']['version'], '1.0.0')
        region1data2 = yaml.safe_load(
            open(os.path.join(self.repodir, 'region1', 'example2.yaml')))
        self.assertEqual(
            region1data2['release']['chart'], 'example2:1.0.0')
        self.assertEqual(region1data2['release']['version'], '1.0.0')
        region1data3 = yaml.safe_load(
            open(os.path.join(self.repodir, 'region1', 'example3.yaml')))
        self.assertEqual(
            region1data3['release']['chart'], 'example3:1.0.0')
        self.assertEqual(region1data3['release']['version'], '1.0.0')

        # Region2 doesn't know about the helm repository.
        region2data = yaml.safe_load(
            open(os.path.join(self.repodir, 'region2', 'example1.yaml')))
        self.assertEqual(region2data['release']['chart'], 'example1:1.0.0')
        self.assertEqual(region2data['release']['version'], '1.0.0')
        region2data2 = yaml.safe_load(
            open(os.path.join(self.repodir, 'region2', 'example2.yaml')))
        self.assertEqual(
            region2data2['release']['chart'], 'example2:1.0.0')
        self.assertEqual(region2data2['release']['version'], '1.0.0')
        region2data3 = yaml.safe_load(
            open(os.path.join(self.repodir, 'region2', 'example3.yaml')))
        self.assertEqual(
            region2data3['release']['chart'], 'example3:1.0.0')
        self.assertEqual(region2data3['release']['version'], '1.0.0')

    def test_write_image_pins(self):
        artifacts = [
            windlass.images.Image(dict(
                name='some/image'))
        ]
        updated_files = windlass.pins.write_pins(
            artifacts, '1.0.0', 'testing1', self.repodir)
        self.assertEqual(updated_files, ['image_pins/testing1.yaml'])

        data = yaml.safe_load(
            open(os.path.join(self.repodir, 'image_pins/testing1.yaml')))
        self.assertEqual(data['images']['some/image'], {'version': '1.0.0'})
        self.assertEqual(data['images']['other/image'], 54321)
