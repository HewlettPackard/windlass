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

"""
An artifact class for cryptographic signatures of artifact.
"""

import windlass.api
import io
import logging
import os


@windlass.api.register_type('signatures')
class DetachedSignature(windlass.api.Artifact):
    def __init__(self, name, data, artifact_type=None):
        init = {'name': name}
        super().__init__(init)
        self.signature_data = data
        self.artifact_type = artifact_type

    def __str__(self):
        return "windlass.signatures.DetachedSignature(name=%s)" % self.name

    def upload(self, remote=None, **kwargs):
        return remote.upload_signature(
            self.artifact_type, self.name, self.export_stream()
        )

    def url(self, version, remote=None, **kwargs):
        if remote is None:
            raise Exception("Missing remote for artifact %s" % self)
        # return remote.compose_url(self, self._upload_path())
        return '<none>'

    def export_stream(self, version=None):
        return io.BytesIO(self.signature_data)

    def export(self, export_dir='.', export_name=None, version=None):
        if export_name is None:
            export_name = self.name
        export_path = os.path.join(export_dir, export_name)
        logging.debug(
            "Exporting signature %s to %s", self.name, export_path
        )
        with open(export_path, 'w') as f:
            f.write(self.export_stream())
        return export_path
