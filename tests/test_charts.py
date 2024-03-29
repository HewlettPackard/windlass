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

import io
import os
import shutil
import tarfile
import tempfile
import yaml

import docker
import git
import requests
import testtools

import windlass.charts
import windlass.exc
import windlass.images
import windlass.tools


class TestCharts(testtools.TestCase):

    def _yaml_load(self, *args, **kwargs):
        return yaml.load(*args, Loader=yaml.SafeLoader, **kwargs)

    def _build_chart(self):
        """Build the test chart.

        Returns a windlass.charts.Chart object for the chart.
        """
        self.client.containers.run(
            'zing/windlass:latest',
            '--debug --build-only products/test-chart.yml',
            remove=True,
            volumes={
                '/var/run/docker.sock': {'bind': '/var/run/docker.sock'},
                self.tempdir.name: {'bind': self.tempdir.name}
            },
            working_dir=self.repodir,
            environment=windlass.tools.load_proxy())
        with open(os.path.join(self.repodir, 'products/test-chart.yml')) as f:
            products = self._yaml_load(f)
        return windlass.charts.Chart(products['charts'][0])

    def setUp(self):
        super().setUp()
        self.client = docker.from_env(version='auto')
        self.tempdir = tempfile.TemporaryDirectory()
        self.repodir = os.path.join(self.tempdir.name, 'fakerepo')
        shutil.copytree('./tests/fakerepo', self.repodir)
        self.repo = git.Repo.init(self.repodir)
        self.repo.git.add('-A')
        self.commitid = self.repo.index.commit('Commit 1').hexsha
        self.chart = self._build_chart()

        # Change to the repo directory so that the package_chart command
        # can find the generated chart and work
        self.saved_cwd = os.getcwd()
        os.chdir(self.repodir)

    def tearDown(self):
        os.chdir(self.saved_cwd)
        self.client.close()
        super().tearDown()

    def test_package_charts(self):
        # Test chart
        with open(os.path.join(self.repodir,
                               'ubuntu-0.0.1.tgz'), 'rb') as stream:
            with tarfile.open(fileobj=stream, mode='r:gz') as tar:
                chart_data = self._yaml_load(
                    tar.extractfile('ubuntu/Chart.yaml')
                )
                values_data = self._yaml_load(
                    tar.extractfile('ubuntu/values.yaml')
                )
        self.assertEqual(chart_data['version'], '0.0.1')
        self.assertEqual(values_data['image']['repository'], 'ubuntu')
        self.assertEqual(values_data['image'].get('registry', None), None)
        self.assertEqual(values_data['image']['tag'], '16.04')

        # Package the chart as -> 2.1.0 for publication
        data = self.chart.package_chart('0.0.1', '2.1.0', registry='reg')

        # Test the output.
        with io.BytesIO(data) as stream:
            with tarfile.open(fileobj=stream, mode='r:gz') as tar:
                chart_data = self._yaml_load(
                    tar.extractfile('ubuntu/Chart.yaml')
                )
                values_data = self._yaml_load(
                    tar.extractfile('ubuntu/values.yaml')
                )

        self.assertEqual(chart_data['version'], '2.1.0')
        self.assertEqual(values_data['image']['repository'], 'ubuntu')
        self.assertEqual(values_data['image']['registry'], 'reg')
        self.assertEqual(values_data['image']['tag'], '2.1.0')

    def test_upload_fallthrough_artifactory_remote(self):
        """Test hook into remote-based chart upload wont break Artifactory."""

        # Test that chart upload correctly falls through to the old
        # (non-remote based) upload code, when passed an artifactory remote.
        # Do this by expecting the exception that occurs in the old code when
        # the bogus url fails.

        remote = windlass.remotes.ArtifactoryRemote(
            username=None, password=None
        )

        with self.assertRaisesRegex(requests.exceptions.MissingSchema,
                                    'Invalid URL.*No scheme supplied. .*'):
            self.chart.upload(
                charts_url='bogus', docker_image_registry='', remote=remote
            )

    def test_repackage_with_bad_values(self):
        del self.chart.data['values']
        self.chart.data['values'] = {
            'non_existing': {'image': {'tag': '{version}'}}}
        e = self.assertRaises(
            windlass.exc.MissingEntryInChartValues,
            self.chart.package_chart, '0.0.1', '2.1.0', registry='reg')
        self.assertEqual(e.missing_key, 'non_existing')
        self.assertEqual(e.chart_name, 'ubuntu')
        self.assertEqual(e.values_filename, 'ubuntu/values.yaml')
        self.assertEqual(e.expected_path, ['non_existing', 'image', 'tag'])
        debug_message = e.debug_message()
        for text in ['non_existing', 'ubuntu', 'ubuntu/values.yaml']:
            self.assertIn(text, str(e))
            self.assertIn(text, debug_message)
