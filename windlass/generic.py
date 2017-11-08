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

import fnmatch
import windlass.api
import glob
import logging
import os
import requests


class LocalArtifactCopyMissing(Exception):
    pass


@windlass.api.register_type('generic')
class Generic(windlass.api.Artifact):
    """Generic artifact type

    No build.

    Download artifact

    Upload artifact
    """
    def __repr__(self):
        return (
            "windlass.generic.Generic(data=dict(name='%s', version='%s',"
            " filename='%s'))" % (
                self.name, self.version, self.data.get('filename')
            )
        )

    def __str__(self):
        result = "<Generic artifact %s version %s" % (self.name, self.version)
        fname = self.data.get('filename')
        if '*' in fname or '?' in fname:
            try:
                result += ' stored in %s>' % (self.get_filename())
            except LocalArtifactCopyMissing:
                result += ' matches %s>' % (fname)
        else:
            result += ' stored in %s>' % fname
        return result

    def get_filename(self):
        # Generic artifacts should be pinned to their filename so that we
        # get find them for promotion, etc.
        filename = self.data.get('filename')
        if os.sep in filename or '/' in filename:
            raise Exception('Filename cannot contain path')
        filenames = glob.glob(filename)
        if len(filenames) != 1:
            if filenames:
                msg = 'Found too many matching files:\n' + '\n'.join(filenames)
            else:
                msg = 'Failed to found artifacts matching %s' \
                      % self.data.get('filename')
            raise LocalArtifactCopyMissing(msg)

        return filenames[0]

    def url(self, version=None, generic_url=None, **kwargs):
        if version and generic_url:
            # This requires Arfifactory and remotes should replace it
            safe_url = generic_url.rstrip('/')
            repo = safe_url[safe_url.rfind('/') + 1:]
            api = safe_url[:safe_url.rfind('/')] + '/api/search/prop'
            params = {'version': version, 'repos': repo}
            uri_list = requests.get(api,
                                    params=params,
                                    verify='/etc/ssl/certs').json()['results']
            for item in uri_list:
                artifact_name = item['uri'].split('/')[-1]
                if fnmatch.fnmatch(artifact_name, self.data.get('filename')):
                    return requests.get(
                        item['uri'],
                        verify='/etc/ssl/certs'
                    ).json()['downloadUri']

            msg = 'Could not find artifact version %s in %s' % (version, repo)
            raise Exception(msg)
        if generic_url:
            return os.path.join(generic_url, artifact_name)

        return self.get_filename()

    @windlass.api.retry()
    @windlass.api.fall_back('generic_url')
    def download(self,
                 version=None,
                 generic_url=None,
                 **kwargs):
        artifact_url = self.url(version or self.version, generic_url)

        resp = requests.get(
            artifact_url,
            verify='/etc/ssl/certs')
        if resp.status_code != 200:
            raise windlass.api.RetryableFailure(
                'Failed to download artifact %s' % (
                    os.path.basename(artifact_url)))

        with open(os.path.basename(artifact_url), 'wb') as fp:
            fp.write(resp.content)

    @windlass.api.retry()
    @windlass.api.fall_back('generic_url', first_only=True)
    def upload(self,
               version=None,
               generic_url=None,
               docker_user=None, docker_password=None,
               **kwargs):
        if not generic_url:
            raise Exception(
                'generic_url not specified. Unable to publish artifact %s' % (
                    self.name))

        local_filename = self.get_filename()
        data = open(local_filename, 'rb').read()
        if version and version.startswith('temp_'):
            temp_path = 'temp/'
        else:
            temp_path = ''
        upload_url = '%s/%s%s%s' % (
            generic_url,
            temp_path,
            local_filename,
            ';version=%s' % version if version else '',)
        auth = requests.auth.HTTPBasicAuth(docker_user, docker_password)

        resp = requests.put(
            upload_url,
            data=data,
            auth=auth,
            verify='/etc/ssl/certs')
        if resp.status_code != 201:
            raise windlass.api.RetryableFailure(
                'Failed (status: %d) to upload %s' % (
                    resp.status_code, upload_url))

        logging.info('%s: Successfully pushed artifact' % self.name)

    def export_stream(self, version=None):
        return open(self.get_filename(), 'rb')

    def export(self, export_dir='.', export_name=None, version=None):
        if export_name is None:
            export_name = os.path.basename(self.get_filename())
        export_path = os.path.join(export_dir, export_name)
        logging.debug(
            "Exporting generic %s to %s", self.name, export_path
        )
        with open(export_path, 'wb') as f:
            f.write(self.export_stream().read())
        return export_path

    def build(self):
        logging.warning(
            '%s is generic artifact and windlass will not build it' % self.name
        )
