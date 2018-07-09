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
import logging
import os
import requests
import requests.auth
import ruamel.yaml
import subprocess
import tarfile
import tempfile
import yaml

import windlass.api
import windlass.exc
import windlass.retry


@windlass.api.register_type('charts')
class Chart(windlass.api.Artifact):
    """Manage charts

    build

    download

    upload
    """
    def __str__(self):
        return "<Helm chart %s>" % self.get_chart_name(
            self.version or self.get_local_version()
        )

    def __repr__(self):
        return "windlass.charts.Chart(data=dict(name='%s', version='%s'))" % (
            self.name, self.version
        )

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

    @windlass.retry.simple()
    @windlass.api.fall_back('charts_url')
    def download(self, version=None, charts_url=None, **kwargs):
        if version is None and self.version is None:
            raise Exception('Must specify version of chart to download.')

        # Download
        if not charts_url:
            raise Exception(
                'charts_url is not specified. Unable to download charts')

        chart_url = self.url(version or self.version, charts_url)
        resp = requests.get(
            chart_url,
            verify='/etc/ssl/certs')
        if resp.status_code != 200:
            raise windlass.exc.RetryableFailure(
                'Failed to download chart %s' % chart_url)

        # Save the chart with the version and don't try and package
        # the chart as a usable chart under the local version.
        # The package_chart can't take a chart and package it under
        # the development version, like we do with images.
        with open(os.path.basename(chart_url), 'wb') as fp:
            fp.write(resp.content)

        # We can't save the chart under the version specified
        # in the original Chart.yaml. The reason being that we
        # will need to recreate the values.yaml file as the
        # chart doesn't reference the same image going forward.

        logging.info('%s: successfully downloaded from %s' % (
            self.name, chart_url))

    def url(self, version=None, charts_url=None, **kwargs):
        chart_name = self.get_chart_name(version or self.version)

        if charts_url:
            return os.path.join(charts_url, chart_name)

        return chart_name

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

    def update_version(self, version):
        """Update the chart version, re-packing if the version changes.

        Does not attempt to remove old version file.
        """
        local_version = self.version or self.get_local_version()
        if version == local_version:
            logging.debug(
                "update_version(chart): No version change (%s)", version
            )
            return
        new_chart_file = self.get_chart_name(version)
        with open(new_chart_file, 'wb') as f:
            f.write(self.package_chart(local_version, version))
        return self.set_version(version)

    @windlass.retry.simple()
    @windlass.api.fall_back(
        'charts_url', 'docker_image_registry', first_only=True)
    def upload(self,
               version=None,
               charts_url=None,
               docker_user=None, docker_password=None,
               docker_image_registry=None,
               **kwargs):
        if 'remote' in kwargs:
            try:
                return kwargs['remote'].upload_chart(
                    self.get_chart_name(version or self.version),
                    self.export_stream(), properties={}
                )
            except windlass.api.NoValidRemoteError:
                # Fall thru to old upload code.
                logging.debug(
                    "No charts endpoint configured for %s", kwargs['remote']
                )
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
        local_chart_name = self.get_chart_name(local_version)

        # Version to upload package as.
        upload_version = version or self.version
        upload_chart_url = self.url(upload_version, charts_url)

        # Start to phase out passing of version to upload.
        if upload_version != local_version:
            logging.warning(
                "Changing chart %s version (to %s) during upload",
                local_chart_name, upload_version
            )

        # Specified version is different to that on the filesystem. So
        # we need to package the chart with the new version and
        # any updated values.
        if upload_version != local_version:
            data = self.package_chart(
                local_version, upload_version,
                registry=docker_image_registry)
        else:  # No version deploy the local development version
            data = open(local_chart_name, 'rb').read()

        logging.info('%s: Pushing chart as %s' % (
            self.name, upload_chart_url))

        status_resp = requests.head(upload_chart_url, verify='/etc/ssl/certs')
        if status_resp.status_code == 200:
            # Chart already exists so don't try and upload it again
            logging.info('%s: Chart already exists at %s' % (
                self.name, upload_chart_url))
        else:
            # Artifact does not exist, push it up.
            auth = requests.auth.HTTPBasicAuth(docker_user, docker_password)
            resp = requests.put(
                upload_chart_url,
                data=data,
                auth=auth,
                verify='/etc/ssl/certs')
            if resp.status_code in (
                    requests.codes.unauthorized, requests.codes.forbidden):
                # No retries in this case.
                raise Exception('Permission error (%s) uploading chart %s' % (
                    resp, upload_chart_url))
            elif resp.status_code != 201:
                raise windlass.exc.RetryableFailure(
                    'Failed (status: %d) to upload %s' % (
                        resp.status_code, upload_chart_url))

            logging.info('%s: Successfully pushed chart' % self.name)

    @windlass.api.fall_back('charts_url')
    def delete(self, version=None, charts_url=None, **kwargs):
        chart_url = self.url(version or self.version, charts_url)
        try:
            os.remove(os.path.basename(chart_url))
        except FileNotFoundError:
            pass

    def export_stream(self, version=None):
        local_version = self.version or self.get_local_version()
        stream_version = version or self.version or local_version

        if stream_version == local_version:
            local_chart_name = self.get_chart_name(local_version)
            return open(local_chart_name, 'rb')
        else:
            cdata = self.package_chart(local_version, stream_version)
            return io.BytesIO(cdata)

    def export(self, export_dir='.', export_name=None, version=None):
        local_version = self.version or self.get_local_version()
        export_version = version or self.version or local_version

        local_chart_name = self.get_chart_name(local_version)
        if export_name is None:
            export_name = self.get_chart_name(export_version)
        export_path = os.path.join(export_dir, export_name)
        logging.debug(
            "Exporting chart %s to %s", local_chart_name, export_path
        )
        # Don't write if the exported chart would be the same as locally saved
        # chart.
        if os.path.abspath(export_path) != os.path.abspath(local_chart_name):
            with open(export_path, 'wb') as f:
                f.write(self.export_stream(export_version).read())
        return export_path
