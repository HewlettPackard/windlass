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

import fixtures
import logging
import testtools
import unittest
from urllib3.exceptions import ReadTimeoutError

import windlass.exc


class TestRetryDecorator(testtools.TestCase):
    def setUp(self):
        super().setUp()
        self.logger = self.useFixture(fixtures.FakeLogger(level=logging.DEBUG))

    def test_retry_fail(self):

        @windlass.retry.simple(retry_backoff=0.1)
        def artifact_func(artifact):
            raise windlass.exc.RetryableFailure('Error')
        mock_artifact = unittest.mock.MagicMock()
        mock_artifact.name = 'ArtifactName'

        e = self.assertRaises(
            windlass.exc.FailedRetriesException,
            artifact_func,
            mock_artifact)
        self.assertEqual(len(e.attempts), 3)

    def test_retry_non_retryable(self):
        run = False

        @windlass.retry.simple(retry_backoff=0.1)
        def artifact_func(artifact):
            nonlocal run
            self.assertFalse(run, 'Retry attempted on non-retryable exception')
            run = True
            raise windlass.exc.WindlassException('Error')
        mock_artifact = unittest.mock.MagicMock()
        mock_artifact.name = 'ArtifactName'

        self.assertRaises(
            windlass.exc.WindlassException,
            artifact_func,
            mock_artifact)

    def test_success(self):
        run = False

        @windlass.retry.simple(retry_backoff=0.1)
        def artifact_func(artifact):
            nonlocal run
            if run:
                return True
            run = True
            raise windlass.exc.RetryableFailure('Error')

        mock_artifact = unittest.mock.MagicMock()
        mock_artifact.name = 'ArtifactName'
        self.assertTrue(
            artifact_func(mock_artifact)
        )

    @unittest.expectedFailure
    def test_retry_fail_timeout(self):

        @windlass.retry.simple(retry_backoff=0.1)
        def artifact_func(artifact):
            raise ReadTimeoutError(
                unittest.mock.MagicMock(),
                unittest.mock.MagicMock(),
                unittest.mock.MagicMock()
            )
        mock_artifact = unittest.mock.MagicMock()
        mock_artifact.name = 'ArtifactName'

        e = self.assertRaises(
            windlass.exc.FailedRetriesException,
            artifact_func,
            mock_artifact)
        self.assertEqual(len(e.attempts), 3)
        e.debug_message()
