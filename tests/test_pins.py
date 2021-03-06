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

import os.path
import shutil
import tempfile

import ruamel.yaml
import testtools
import yaml

import windlass.charts
import windlass.generic
import windlass.images
import windlass.pins


class TestPins(testtools.TestCase):

    def _yaml_load(self, *args, **kwargs):
        return yaml.load(*args, Loader=yaml.SafeLoader, **kwargs)

    def setUp(self):
        super().setUp()
        self.tempdir = tempfile.TemporaryDirectory()
        # self.repodir = self.tempdir.name
        self.repodir = os.path.join(self.tempdir.name, 'integrationrepo')
        self.repodir_rhs = os.path.join(self.tempdir.name,
                                        'integrationrepo_rhs')
        shutil.copytree('./tests/integrationrepo', self.repodir)
        shutil.copytree('./tests/integrationrepo_rhs', self.repodir_rhs)

        self.yaml = ruamel.yaml.YAML()

    def test_write_override_yaml_configuration(self):
        repodir = os.path.join(self.tempdir.name, 'override')
        shutil.copytree('./tests/integrationrepo-override', repodir)

        artifacts = [
            windlass.generic.Generic(dict(
                name='myapp4windows.tgz',
                version='0.1')),
            windlass.generic.Generic(dict(
                name='myapp4macos',
                version='0.1')),
            windlass.charts.Chart(dict(
                name='example1')),
        ]

        updated_files = windlass.pins.write_pins(
            artifacts, 'testing1', repodir, metadata={
                'item': 'value'
            })

        self.assertEqual(updated_files, ['aws/api.yaml'])

        with open(os.path.join(repodir, 'aws/api.yaml')) as f:
            data = self._yaml_load(f)
        self.assertEqual(data, {
            'configuration': {'my_app_mac': '0.1',
                              'my_app_win': '0.1',
                              # Not managed by the override pinning
                              'image': {
                                  'registry': 'somewhere'
                              }}
        })

    def test_write_override_yaml_configuration_unknown_artifact(self):
        repodir = os.path.join(self.tempdir.name, 'override')
        shutil.copytree('./tests/integrationrepo-override', repodir)

        conf = os.path.join(repodir, 'product-integration.yaml')
        with open(conf, 'w') as fp:
            fp.write("""---
pins:
  override:
    type: OverrideYamlConfiguration
    api:
      file: aws/api.yaml
      artifacttype: windlass.generic.Generic
      values:
        - yamlpath: 'configuration.my_app_win'
          value: "{{ artifacts['missingthingy'].version }}"
""")

        artifacts = [
            windlass.generic.Generic(dict(
                name='myapp4windows.tgz',
                version='0.1')),
            windlass.charts.Chart(dict(
                name='example1')),
        ]

        updated_files = windlass.pins.write_pins(
            artifacts, 'testing1', repodir, metadata={
                'item': 'value'
            })

        # In this case we have not overriden the yaml configuration
        # as we have not updated an artifact
        self.assertEqual(updated_files, [])

    def test_read_override_pins(self):
        repodir = os.path.join(self.tempdir.name, 'override')
        shutil.copytree('./tests/integrationrepo-override', repodir)

        artifacts = windlass.pins.read_pins(repodir)
        self.assertEqual(len(artifacts), 0)
        # self.assertEqual(len(artifacts), 2)
        # self.assertEqual(artifacts[0].name, 'myapp4windows.tgz')
        # self.assertEqual(artifacts[0].version, 'oldversion')
        # self.assertEqual(artifacts[1].name, 'myapp4macos')
        # self.assertEqual(artifacts[1].version, 'oldversion')

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
        self.assertEqual(
            artifact_types['some/image2'].data['zing-metadata'],
            {'stuff': 112233})
        self.assertEqual(pins['other/image2'], 54321)
        self.assertIsInstance(
            artifact_types['other/image2'], windlass.images.Image)
        self.assertEqual(artifact_types['other/image2'].devtag, 'latest')

        # Charts
        self.assertEqual(pins['example1'], '0.0.1')
        self.assertIsInstance(artifact_types['example1'],
                              windlass.charts.Chart)

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

        self.assertEqual(sorted_updates[0]['name'], 'example1')
        self.assertEqual(sorted_updates[0]['lhs'].version, '0.0.1')
        self.assertEqual(sorted_updates[0]['rhs'].version, '0.0.2')
        self.assertEqual(sorted_updates[1]['name'], 'some/image')
        self.assertEqual(sorted_updates[1]['lhs'].version, 12345)
        self.assertEqual(sorted_updates[1]['rhs'].version, 12346)

    def test_write_chart_pins(self):
        artifacts = [
            windlass.charts.Chart(dict(
                name='example1',
                version='1.0.0')),
            windlass.charts.Chart(dict(
                name='example2',
                version='1.0.0')),
            windlass.charts.Chart(dict(
                name='example3',
                version='1.0.0')),
            ]
        updated_files = windlass.pins.write_pins(
            artifacts, 'repo', self.repodir)
        self.assertEqual(updated_files, [
            'region1/example1.yaml',
            'region1/example2.yaml',
            'region1/example3.yaml',
            'region2/example1.yaml',
            'region2/example2.yaml',
            'region2/example3.yaml'])

        with open(os.path.join(self.repodir, 'region1', 'example1.yaml')) as f:
            region1data1 = yaml.safe_load(f)
        self.assertEqual(
            region1data1['release']['chart'], 'staging-charts/example1:1.0.0')
        with open(os.path.join(self.repodir, 'region1', 'example2.yaml')) as f:
            region1data2 = yaml.safe_load(f)
        self.assertEqual(
            region1data2['release']['chart'], 'example2:1.0.0')
        with open(os.path.join(self.repodir, 'region1', 'example3.yaml')) as f:
            region1data3 = yaml.safe_load(f)
        self.assertEqual(
            region1data3['release']['chart'], 'example3:1.0.0')

        # Region2 doesn't know about the helm repository.
        with open(os.path.join(self.repodir, 'region2', 'example1.yaml')) as f:
            region2data1 = yaml.safe_load(f)
        self.assertEqual(region2data1['release']['chart'], 'example1:1.0.0')
        with open(os.path.join(self.repodir, 'region2', 'example2.yaml')) as f:
            region2data2 = yaml.safe_load(f)
        self.assertEqual(
            region2data2['release']['chart'], 'example2:1.0.0')
        with open(os.path.join(self.repodir, 'region2', 'example3.yaml')) as f:
            region2data3 = yaml.safe_load(f)
        self.assertEqual(
            region2data3['release']['chart'], 'example3:1.0.0')

    def test_write_image_pins(self):
        artifacts = [
            windlass.images.Image(dict(
                name='some/image',
                version='1.0.0'))
        ]
        updated_files = windlass.pins.write_pins(
            artifacts, 'testing1', self.repodir, metadata={
                'item': 'value'
            })
        self.assertEqual(updated_files, ['image_pins/testing1.yaml'])

        with open(
                os.path.join(self.repodir, 'image_pins', 'testing1.yaml')
        ) as f:
            data = yaml.safe_load(f)

        self.assertEqual(
            data['images']['some/image'],
            {'version': '1.0.0', 'zing-metadata': {'item': 'value'}})
        self.assertEqual(data['images']['other/image'], 54321)
