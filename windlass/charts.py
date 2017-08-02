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

import windlass.api
import io
import logging
import os
import requests
import requests.auth
import ruamel.yaml
import subprocess
import tarfile
import tempfile
import yaml


@windlass.api.register_type('charts')
class Chart(windlass.api.Artifact):
    """Manage charts

    build

    download

    upload
    """

    def get_chart_dir(self):
        # The directory containing the chart must match the name of the chart.
        repopath = os.path.abspath('.')
        return os.path.join(repopath, self.data.get('location', ''), self.name)

    def get_chart_name(self, version):
        return '%s-%s.tgz' % (self.name, version)

    def get_local_version(self):
        chartdir = self.get_chart_dir()
        with open(os.path.join(chartdir, 'Chart.yaml')) as fp:
            chart = yaml.load(fp)

        return chart['version']

    def build(self):
        "Builds local chart with developer specified version"
        chartdir = self.get_chart_dir()
        logging.info('Building %s in %s' % (self.name, chartdir))

        # Can use --version here also
        cmd = ['helm', 'package', '--save=false', chartdir]

        if subprocess.call(cmd) != 0:
            raise Exception('Failed to build chart: %s' % self.name)

    def download(self, version, charts_url, **kwargs):
        # Download
        if not charts_url:
            raise Exception(
                'charts_url is not specified. Unable to download charts')

        chart_name = self.get_chart_name(version)
        resp = requests.get(
            os.path.join(charts_url, chart_name),
            verify='/etc/ssl/certs')
        if resp.status_code != 200:
            raise Exception(
                'Failed to download chart %s' % chart_name)

        local_version = self.get_local_version()
        local_file = self.get_chart_name(local_version)
        with open(local_file, 'wb') as fp:
            fp.write(resp.content)

    def upload(self,
               version=None, charts_url=None,
               docker_user=None, docker_password=None,
               **kwargs):
        # TODO(kerrin) can we reuse the docker_* credentials like this,
        # it works for artifactory, not sure about AWS.
        if not charts_url:
            raise Exception(
                'charts_url not specified. Unable to publish chart')

        with tempfile.NamedTemporaryFile() as tmp_file:
            # The location needs to be set in order to find the development
            # version of the chart.
            local_version = self.get_local_version()
            local_chart_name = self.get_chart_name(local_version)

            if version:
                chart_file = os.path.join(self.name, 'Chart.yaml')
                tfile = tarfile.open(local_chart_name, 'r:gz')
                chart_yaml = tfile.extractfile(chart_file)
                chart_data = ruamel.yaml.load(
                    chart_yaml, Loader=ruamel.yaml.RoundTripLoader)
                chart_data['version'] = version

                chart_name = self.get_chart_name(version)
                with tarfile.open(tmp_file.name, 'w:gz') as out:
                    for member in tfile.getmembers():
                        if member.name == chart_file:
                            # Override the size of the file
                            datastr = ruamel.yaml.dump(
                                chart_data,
                                Dumper=ruamel.yaml.RoundTripDumper)
                            databytes = datastr.encode('utf-8')
                            member.size = len(databytes)
                            out.addfile(member, io.BytesIO(databytes))
                        else:
                            out.addfile(member, tfile.extractfile(member.name))

                out_filename = tmp_file.name
            else:  # No version deploy the local development version
                chart_name = out_filename = local_chart_name

            logging.info('%s: Pushing chart as %s' % (self.name, chart_name))

            auth = requests.auth.HTTPBasicAuth(docker_user, docker_password)
            resp = requests.put(
                os.path.join(charts_url, chart_name),
                data=open(out_filename, 'rb'),
                auth=auth,
                verify='/etc/ssl/certs')
            if resp.status_code != 201:
                raise Exception(
                    'Failed (status: %d) to upload %s' % (
                        resp.status_code, local_chart_name))

        logging.info('%s: Successfully pushed chart' % self.name)
