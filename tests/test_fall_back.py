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

import testtools

import windlass.api


class FallbackFailure(Exception):
    pass


class TestFallBack(testtools.TestCase):
    """Test the fall_back decorator"""
    def setUp(self):
        super().setUp()
        self.artifact = windlass.api.Artifact({'name': 'fake'})

        @windlass.api.fall_back('x')
        def f(a, x):
            if x != 1:
                raise FallbackFailure('Bad value: %s' % x)
            return x

        self.fallback_func = f

    def test_fall_back(self):
        """Test that the fall_back decorator retry works"""
        result = self.fallback_func(self.artifact, x=[0, 2, 1])
        self.assertEqual(result, 1)

    def test_fall_back_failure(self):
        """Test that fall_back failures re-raises the original exception"""
        with testtools.ExpectedException(FallbackFailure):
            self.fallback_func(self.artifact, x=[0, 2, 3])
