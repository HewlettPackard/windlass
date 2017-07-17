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

from collections import defaultdict
import logging
import multiprocessing


class Artifact(object):
    """Artifact type

    Contains methods to control how to manage artifacts of a
    particular type.
    """

    def __init__(self, data):
        self.data = data

    @property
    def priority(self):
        return self.data.get('priority', 0)

    @property
    def name(self):
        return self.data['name']

    def url(self, version=None):
        raise NotImplementedError('url not implemented')

    def build(self):
        raise NotImplementedError('build not implemented')

    def download(self, version, **kwargs):
        raise NotImplementedError('download not implemented')

    def upload(self, version, **kwargs):
        raise NotImplementedError('upload not implemented')


class Windlass(object):

    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.failure_occured = multiprocessing.Event()
        # This is only used by windlass.py and should be removed?
        self.registry_ready = multiprocessing.Event()

    def wait_for_procs(self):
        while True:
            if self.failure_occured.wait(0.1):
                for p in self.procs:
                    p.terminate()
                logging.info('Killed all processes')
                return False

            if len([p for p in self.procs if p.is_alive()]) == 0:
                return True

    def work(self, process, artifact, *args, **kwargs):
        try:
            process(artifact, *args, **kwargs)
        except Exception:
            logging.exception(
                'Processing image %s failed with exception', artifact.name)
            self.failure_occured.set()

    def run(self, processor, *args, **kwargs):
        # Reset events.
        self.procs = []

        d = defaultdict(list)
        for artifact in self.artifacts:
            k = artifact.priority
            d[k].append(artifact)

        failed = False
        for i in reversed(sorted(d.keys())):
            for artifact in d[i]:
                p = multiprocessing.Process(
                    target=self.work,
                    args=(
                        processor,
                        artifact,
                    ) + args,
                    kwargs=kwargs,
                    name=artifact.name,
                )
                p.start()
                self.procs.append(p)
            if not self.wait_for_procs():
                failed = True

        if failed:
            raise Exception('Failed to process artifacts')

    def list(self, version=None, **kwargs):
        for artifact in self.artifacts:
            yield artifact.url(version, **kwargs)

    def build(self):
        self.run(lambda artifact: artifact.build())

    def download(self, version, *args, **kwargs):
        self.run(lambda artifact: artifact.download(version, *args, **kwargs))

    def upload(self, version, *args, **kwargs):
        self.run(lambda artifact: artifact.upload(version, *args, **kwargs))


def setupLogging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level, format='%(asctime)s %(levelname)s %(message)s')
