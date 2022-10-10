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

import docker
from git import Repo
import os
from requests import get
from shutil import copytree
from tempfile import TemporaryDirectory
import testtools
from testtools.matchers import Contains
from testtools.matchers import Equals
import time

import windlass.api
import windlass.images
import windlass.tools


class FakeRegistry(testtools.TestCase):

    @classmethod
    def setUpClass(self):
        self.client = docker.from_env(version='auto')
        self.registry = self.client.containers.run(
            'registry:2',
            detach=True,
            ports={'5000/tcp': None})

        self.registry.reload()
        self.registry_port = int(
            self.registry.ports['5000/tcp'][0]['HostPort']
        )
        self.registry_url = "http://127.0.0.1:%d/" % self.registry_port

    @classmethod
    def tearDownClass(self):
        # Remove all associated with this test.
        for img in self.client.images.list():
            for tag in img.tags:
                if tag.startswith('127.0.0.1:%d' % self.registry_port):
                    self.client.images.remove(tag)

        self.registry.kill()
        self.registry.remove()
        self.client.close()


class FakeWindlassObject(testtools.TestCase):

    def test_list(self):
        artifacts = [
            windlass.charts.Chart(dict(
                name='example1')),
            windlass.images.Image(dict(
                name='some/image')),
        ]
        g = windlass.api.Windlass(artifacts=artifacts)
        urls = g.list(version='0.0.0-sha1')
        self.assertEqual(
            urls, ['example1-0.0.0-sha1.tgz', 'some/image:0.0.0-sha1'])


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

    def test_bad_build(self):
        container = self.client.containers.run(
            'zing/windlass:latest',
            ('--debug --push-docker-registry 127.0.0.1:%d '
             '%s/products/bad.yml') % (
                self.registry_port, self.repodir
                ),
            volumes={'/var/run/docker.sock': {'bind': '/var/run/docker.sock'},
                     self.repodir: {'bind': self.repodir}},
            working_dir=self.repodir,
            environment=windlass.tools.load_proxy(),
            detach=True
        )
        self.addCleanup(container.remove)
        start = time.time()
        while container.status in ['running', 'created']:
            time.sleep(2)
            container.reload()
            if time.time() - start > 30:
                break
        if container.status in ['running', 'exited']:
            docker_logs = container.logs().decode()
            self.addDetail(
                'docker logs', testtools.content.text_content(
                    str(docker_logs)))
        self.addDetail(
            'docker attributes', testtools.content.text_content(
                str(container.attrs))
            )
        self.assertEqual(container.status, 'exited')
        self.assertEqual(container.attrs['State']['ExitCode'], 1)
        self.assertNotIn('Traceback', docker_logs)
        self.assertIn('Build failed with output', docker_logs)

    def test_fake_repo_build_and_push(self):
        self.client.containers.run(
            'zing/windlass:latest',
            ('--debug --push-docker-registry 127.0.0.1:%d '
             '%s/products/test.yml') % (
                self.registry_port, self.repodir
                ),
            remove=True,
            volumes={'/var/run/docker.sock': {'bind': '/var/run/docker.sock'},
                     self.repodir: {'bind': self.repodir}},
            working_dir=self.repodir,
            environment=windlass.tools.load_proxy(),
        )
        # TODO(kerrin) disable partial image until we recognize remote urls
        # self.check_proper_image_build('partial')
        self.check_proper_image_build('full')

    def test_fake_repo_build_and_bad_push(self):
        container = self.client.containers.run(
            'zing/windlass:latest',
            ('--debug --push-docker-registry 127.0.0.1:%d '
             '%s/products/test.yml') % (
                1000, self.repodir
                ),
            volumes={'/var/run/docker.sock': {'bind': '/var/run/docker.sock'},
                     self.repodir: {'bind': self.repodir}},
            working_dir=self.repodir,
            environment=windlass.tools.load_proxy(),
            detach=True
        )
        self.addCleanup(container.remove)
        start = time.time()
        while container.status in ['running', 'created']:
            time.sleep(2)
            container.reload()
            if time.time() - start > 30:
                break
        if container.status in ['running', 'exited']:
            docker_logs = container.logs().decode()
            self.addDetail(
                'docker logs', testtools.content.text_content(
                    str(docker_logs)))
        self.addDetail(
            'docker attributes', testtools.content.text_content(
                str(container.attrs))
            )
        self.assertEqual(container.status, 'exited')
        self.assertEqual(container.attrs['State']['ExitCode'], 1)
        self.assertNotIn('Traceback', docker_logs)
        self.assertIn('Error pushing or pulling artifact', docker_logs)

    def check_proper_image_build(self, imagename):
        fullimagename = '127.0.0.1:%s/fakerepo%s' % (
            self.registry_port, imagename)
        try:
            self.client.images.get(fullimagename)
        except docker.errors.ImageNotFound:
            pass
        else:
            self.fail("Image %s exists. It shouldn't" % fullimagename)

        # docker 3.0.1 changed api for pull method
        image = self.client.images.pull(fullimagename)
        _, tags = zip(*(t.split('/')[-1].split(':') for t in image.tags))
        self.expectThat(tags, Contains('latest'),
                        '%s image missing latest tag' % imagename)
        self.expectThat(tags, Contains('branch_master'),
                        '%s image missing branch tag' % imagename)
        self.expectThat(tags, Contains('ref_' + self.commitid),
                        '%s image missing commit tag')
        with open(
                'tests/fakerepo/%scontext/image_content.txt' % imagename
        ) as f:
            self.expectThat(
                self.client.containers.run(image, remove=True).decode(),
                Equals(f.read()),
                '%s image build is not valid',
            )
        response = get(
            'http://127.0.0.1:%d/v2/fakerepo%s/tags/list' % (
                self.registry_port, imagename))
        self.assertThat(response.status_code, Equals(200))
        self.assertThat(
            response.json()['name'], Equals('fakerepo%s' % imagename))

    def test_version_upload(self):
        self.client.containers.run(
            'zing/windlass:latest',
            ('--debug --push-docker-registry 127.0.0.1:%d '
             '--push-version=12345 '
             '%s/products/test.yml') % (
                 self.registry_port, self.repodir
            ),
            remove=True,
            volumes={'/var/run/docker.sock': {'bind': '/var/run/docker.sock'},
                     self.repodir: {'bind': self.repodir}},
            working_dir=self.repodir,
            environment=windlass.tools.load_proxy(),
        )

        fullimagename = '127.0.0.1:%s/fakerepofull:12345' % (
            self.registry_port)

        try:
            self.client.images.get(fullimagename)
        except docker.errors.ImageNotFound:
            pass
        else:
            self.fail("Image %s exists. It shouldn't" % fullimagename)

        # We can pull image from registry
        self.client.images.pull(fullimagename)

    def test_download(self):
        # pull alpine:3.5
        test_image_name = '127.0.0.1:%d/testing/download:12345' % (
            self.registry_port)
        self.client.images.pull('alpine:3.5')
        self.client.api.tag('alpine:3.5', test_image_name)
        self.client.images.push(test_image_name)
        self.client.api.remove_image(test_image_name)

        self.client.containers.run(
            'zing/windlass:latest',
            ('--debug --download-docker-registry 127.0.0.1:%d '
             '--download --no-push --download-version 12345 '
             '%s/products/test-download.yaml') % (
                 self.registry_port, self.repodir),
            remove=True,
            volumes={'/var/run/docker.sock': {'bind': '/var/run/docker.sock'},
                     self.repodir: {'bind': self.repodir}},
            working_dir=self.repodir,
            environment=windlass.tools.load_proxy(),
        )

        self.client.images.get('testing/download:12345')
        self.client.images.get('testing/download:latest')

        self.client.api.remove_image('testing/download:12345')
        self.client.api.remove_image('testing/download:latest')

    def test_product_inteagrtion_repo(self):
        # pull alpine:3.5
        test_image_name = '127.0.0.1:%d/testing/download:12345' % (
            self.registry_port)
        self.client.images.pull('alpine:3.5')
        self.client.api.tag('alpine:3.5', test_image_name)
        self.client.images.push(test_image_name)
        self.client.api.remove_image(test_image_name)

        self.client.containers.run(
            'zing/windlass:latest',
            ('--debug --download-docker-registry 127.0.0.1:%d '
             '--download --no-push '
             '--product-integration-repo %s') % (
                 self.registry_port, self.repodir),
            remove=True,
            volumes={'/var/run/docker.sock': {'bind': '/var/run/docker.sock'},
                     self.repodir: {'bind': self.repodir}},
            working_dir=self.repodir,
            environment=windlass.tools.load_proxy(),
        )

        self.client.images.get('testing/download:12345')
        self.client.images.get('testing/download:latest')

        self.client.api.remove_image('testing/download:12345')
        self.client.api.remove_image('testing/download:latest')
