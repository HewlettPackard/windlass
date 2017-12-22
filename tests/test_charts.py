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
import windlass.charts
import windlass.images
import windlass.tools
import git
import io
import os
import shutil
import tarfile
import tempfile
import testtools
import yaml


class TestCharts(testtools.TestCase):

    def setUp(self):
        super().setUp()
        self.client = docker.from_env(version='auto')
        self.tempdir = tempfile.TemporaryDirectory()
        self.repodir = os.path.join(self.tempdir.name, 'fakerepo')
        shutil.copytree('./tests/fakerepo', self.repodir)
        self.repo = git.Repo.init(self.repodir)
        self.repo.git.add('-A')
        self.commitid = self.repo.index.commit('Commit 1').hexsha

        # Change to the repo directory so that the package_chart command
        # can find the generated chart and work
        self.saved_cwd = os.getcwd()
        os.chdir(self.repodir)

    def tearDown(self):
        os.chdir(self.saved_cwd)
        super().tearDown()

    def test_package_charts(self):
        # This required to be built, and latest. This has the helm
        # package installed in order to build the helm package.
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

        products = yaml.load(
            open(os.path.join(self.repodir, 'products/test-chart.yml')))
        chart = windlass.charts.Chart(products['charts'][0])

        # Test chart
        stream = open(os.path.join(self.repodir, 'ubuntu-0.0.1.tgz'), 'rb')
        tar = tarfile.open(fileobj=stream, mode='r:gz')
        chart_data = yaml.load(tar.extractfile('ubuntu/Chart.yaml'))
        self.assertEqual(chart_data['version'], '0.0.1')
        values_data = yaml.load(tar.extractfile('ubuntu/values.yaml'))
        self.assertEqual(values_data['image']['repository'], 'ubuntu')
        self.assertEqual(values_data['image'].get('registry', None), None)
        self.assertEqual(values_data['image']['tag'], '16.04')

        # Package the chart as -> 2.1.0 for publication
        data = chart.package_chart('0.0.1', '2.1.0', registry='reg')

        # Test the output.
        stream = io.BytesIO(data)
        tar = tarfile.open(fileobj=stream, mode='r:gz')
        chart_data = yaml.load(tar.extractfile('ubuntu/Chart.yaml'))
        self.assertEqual(chart_data['version'], '2.1.0')

        values_data = yaml.load(tar.extractfile('ubuntu/values.yaml'))
        self.assertEqual(values_data['image']['repository'], 'ubuntu')
        self.assertEqual(values_data['image']['registry'], 'reg')
        self.assertEqual(values_data['image']['tag'], '2.1.0')
