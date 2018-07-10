#
# (c) Copyright 2018 Hewlett Packard Enterprise Development LP
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

"""Tests for the windlass.testing module"""

import windlass.remotes
import windlass.testing
import logging

import fixtures
import testtools
import unittest.mock


class TestFakeECRConnector(testtools.TestCase):

    def test_upload_without_region(self):
        # This test should eventually change to ensuring that not setting
        # region causes a failure.
        self.logger = self.useFixture(fixtures.FakeLogger(level=logging.DEBUG))
        c = windlass.testing.FakeECRConnector(
            windlass.remotes.AWSCreds('fake_user', 'fake_secret', None)
        )
        c.upload('fake_image:latest')
        self.assertIn(
            "Setting AWS region to 'test-region'", self.logger.output
        )

    def test_upload(self):
        c = windlass.testing.FakeECRConnector(
            windlass.remotes.AWSCreds('fake_user', 'fake_secret', 'fake-region')
        )
        img = 'fake_image:latest'
        self.assertIn(img, c.upload(img))


class TestFakeAWSRemote(testtools.TestCase):

    def test_windlass_upload(self):
        """Test multiprocessed windlass upload on FakeAWSRemote"""
        artifacts = [
            windlass.images.Image(
                dict(name='some/image', version='1.0.0')
            ),
            windlass.charts.Chart(
                dict(name='some/chart', version='1.0.0')
            ),
            windlass.generic.Generic(
                dict(
                    name='some/generic', version='1.0.0',
                    filename='generic.bin'
                )
            ),
        ]
        windlass_obj = windlass.api.Windlass(
            artifacts=windlass.api.Artifacts(artifacts=artifacts)
        )
        r = windlass.testing.FakeAWSRemote(
            'fake_user', 'fake_secret', 'fake-region'
        )
        r.setup_docker()
        r.setup_charts('fake_charts_bucket')
        r.setup_generic('fake_generic_bucket')

        # Patch the upload methods for charts & generics, at as low a level as
        # possible.
        # Note - using a custom None-returning patch function since the usual
        # Mock object returned by patch() is not pickleable.
        def pf(*args, **kwargs):
            return None
        with unittest.mock.patch('windlass.charts.Chart.export_stream', new=pf):
            with unittest.mock.patch('windlass.generic.Generic.upload', new=pf):
                windlass_obj.upload(
                    remote=r, charts_url='None', docker_image_registry='None',
                    generic_url='None',
                )
