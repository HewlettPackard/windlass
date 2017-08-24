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

    def download(self, version=None, charts_url=None, **kwargs):
        if version is None and self.version is None:
            raise Exception('Must specify version of chart to download.')

        # Download
        if not charts_url:
            raise Exception(
                'charts_url is not specified. Unable to download charts')

        chart_name = self.get_chart_name(version or self.version)
        resp = requests.get(
            os.path.join(charts_url, chart_name),
            verify='/etc/ssl/certs')
        if resp.status_code != 200:
            raise Exception(
                'Failed to download chart %s' % chart_name)

        # Save the chart with the version and don't try and package
        # the chart as a usable chart under the local version.
        # The package_chart can't take a chart and package it under
        # the development version, like we do with images.
        with open(chart_name, 'wb') as fp:
            fp.write(resp.content)

        # We can't save the chart under the version specified
        # in the original Chart.yaml. The reason being that we
        # will need to recreate the values.yaml file as the
        # chart doesn't reference the same image going forward.

    def package_chart(self, local_version, version=None, **kwargs):
        '''Package chart

        Take the chart file and process it, returning the contents
        of a chart with, different version, and apply all the values
        specified in the configuration file.
        '''
        local_chart_name = self.get_chart_name(local_version)

        tfile = tarfile.open(local_chart_name, 'r:gz')

        def get_data(filename):
            membername = os.path.join(self.name, filename)
            yaml = tfile.extractfile(membername)
            return membername, ruamel.yaml.load(
                yaml, Loader=ruamel.yaml.RoundTripLoader)

        chart_file, chart_data = get_data('Chart.yaml')
        chart_data['version'] = version

        values_file, values_data = get_data('values.yaml')
        values = self.data.get('values', None)
        if values:
            # TODO(kerrin) expand the amount of data available
            # for users to control
            data = {
                'version': version,
                'name': self.name,
            }
            data.update(kwargs)

            def expand_values(source, expanded):
                for key, value in source.items():
                    if isinstance(value, dict):
                        expand_values(value, expanded[key])
                    else:
                        newvalue = value.format(**data)
                        expanded[key] = newvalue
            # Update by reference the values_data dictionary based on
            # the format of the supplied values field.
            expand_values(values, values_data)

        with tempfile.NamedTemporaryFile() as tmp_file:
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
                    elif member.name == values_file:
                        # Override the size of the file
                        datastr = ruamel.yaml.dump(
                            values_data,
                            Dumper=ruamel.yaml.RoundTripDumper)
                        databytes = datastr.encode('utf-8')
                        member.size = len(databytes)
                        out.addfile(member, io.BytesIO(databytes))
                    else:
                        out.addfile(member, tfile.extractfile(member.name))

            fp = open(tmp_file.name, 'rb')
            return fp.read()

    def upload(self,
               version=None,
               charts_url=None,
               docker_user=None, docker_password=None,
               docker_image_registry=None,
               **kwargs):
        # TODO(kerrin) can we reuse the docker_* credentials like this,
        # it works for artifactory, not sure about AWS.
        if not charts_url:
            raise Exception(
                'charts_url not specified. Unable to publish chart')

        # local_version is the version of chart on the local
        # filesystem. We need this to find the chart to upload.
        # If self.version is not set, we call get_local_version
        # which will look up the local Chart.yaml file, so the
        # location of the chart sources will be required for this
        # to work.
        local_version = self.version or self.get_local_version()

        # Version to upload package as.
        upload_version = version or self.version
        upload_chart_name = self.get_chart_name(upload_version)

        # Specified version is different to that on the filesystem. So
        # we need to package the chart with the new version and
        # any updated values.
        if upload_version != local_version:
            data = self.package_chart(
                local_version, upload_version,
                registry=docker_image_registry)
        else:  # No version deploy the local development version
            local_chart_name = self.get_chart_name(local_version)
            data = open(local_chart_name, 'rb').read()

        logging.info('%s: Pushing chart as %s' % (
            self.name, upload_chart_name))

        auth = requests.auth.HTTPBasicAuth(docker_user, docker_password)
        resp = requests.put(
            os.path.join(charts_url, upload_chart_name),
            data=data,
            auth=auth,
            verify='/etc/ssl/certs')
        if resp.status_code != 201:
            raise Exception(
                'Failed (status: %d) to upload %s' % (
                    resp.status_code, upload_chart_name))

        logging.info('%s: Successfully pushed chart' % self.name)
