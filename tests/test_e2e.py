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
import windlass.images
from git import Repo
import os
from requests import get
from shutil import copytree
from tempfile import TemporaryDirectory
import test.support
import testtools
from testtools.matchers import Contains
from testtools.matchers import Equals


class FakeRegistry(testtools.TestCase):

    @classmethod
    def setUpClass(self):
        self.registry_port = test.support.find_unused_port()
        self.client = docker.from_env(version='auto')
        self.registry = self.client.containers.run(
            'registry:2',
            detach=True,
            ports={'5000/tcp': self.registry_port})

    @classmethod
    def tearDownClass(self):
        self.registry.kill()
        self.registry.remove()


class Test_E2E_SelfBuild(FakeRegistry):

    def test_tags_in_registry(self):
        base = os.path.dirname(os.path.dirname(__file__))
        # This uses the zing/windlass:latest image build during the tox -ebuild
        # step in ci/check.sh
        # This aslo rebuilds the image, we should only do this once and use
        # it to build and test other images.
        self.client.containers.run(
            'zing/windlass:latest',
            '--debug --directory %s --repository 127.0.0.1:%d dev' % (
                base, self.registry_port,
                ),
            remove=True,
            volumes={'/var/run/docker.sock': {'bind': '/var/run/docker.sock'},
                     base: {'bind': base}},
            environment=windlass.images.load_proxy(),
            )

        response = get(
            'http://127.0.0.1:%d/v2/zing/windlass/tags/list' % (
                self.registry_port))
        self.assertThat(response.status_code, Equals(200))
        self.assertThat(response.json()['name'], Equals('zing/windlass'))


class Test_E2E_FakeRepo(FakeRegistry):

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.tempdir = TemporaryDirectory()
        self.repodir = os.path.join(self.tempdir.name, 'fakerepo')
        copytree('./tests/fakerepo', self.repodir)
        self.repo = Repo.init(self.repodir)
        self.repo.git.add('-A')
        self.commitid = self.repo.index.commit('Commit 1').hexsha

    def test_fake_repo(self):
        self.client.containers.run(
            'zing/windlass:latest',
            '--debug --directory %s --repository 127.0.0.1:%d test' % (
                self.repodir, self.registry_port,
                ),
            remove=True,
            volumes={'/var/run/docker.sock': {'bind': '/var/run/docker.sock'},
                     self.repodir: {'bind': self.repodir}},
            environment=windlass.images.load_proxy(),
            )
        self.check_proper_image_build('partial')
        self.check_proper_image_build('full')

    def check_proper_image_build(self, imagename):
        image = self.client.images.get('127.0.0.1:%s/fakerepo%s' %
                                       (self.registry_port, imagename))
        _, tags = zip(*(t.split('/')[-1].split(':') for t in image.tags))
        self.expectThat(tags, Contains('latest'),
                        '%s image missing latest tag' % imagename)
        self.expectThat(tags, Contains('branch_master'),
                        '%s image missing branch tag' % imagename)
        self.expectThat(tags, Contains('ref_' + self.commitid),
                        '%s image missing commit tag')
        self.expectThat(self.client.containers.run(image,
                                                   remove=True).decode(),
                        Equals(open('tests/fakerepo/%scontext/image_content.'
                                    'txt' % imagename).read()),
                        '%s image build is not valid')
