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

import windlass.api
import windlass.charts
import windlass.images
import testtools


class TestAPI(testtools.TestCase):
    def setUp(self):
        super().setUp()
        artifacts = [
            windlass.images.Image(dict(name='some/image', version='1.0.0')),
            windlass.charts.Chart(
                dict(name='some/chart', version='1.0.0', myattr=True)
            ),
        ]
        self.windlass = windlass.api.Windlass(
            artifacts=windlass.api.Artifacts(artifacts=artifacts)
        )

    def test_in_place_filter_artifacts_by_type(self):
        self.windlass.filter_artifacts_in_place(
            lambda a: isinstance(a, windlass.images.Image)
        )
        self.assertEqual(len(list(self.windlass.artifacts)), 1)
        self.assertIsInstance(
            list(self.windlass.artifacts)[0], windlass.images.Image
        )

    def test_in_place_filter_artifacts_by_attribute(self):
        self.windlass.filter_artifacts_in_place(lambda a: a.data.get('myattr'))
        self.assertEqual(list(self.windlass.artifacts)[0].data['myattr'], True)
        self.assertEqual(len(list(self.windlass.artifacts)), 1)

    def test_in_place_filter_artifacts_remove_all(self):
        self.windlass.filter_artifacts_in_place(lambda a: False)
        self.assertEqual(len(list(self.windlass.artifacts)), 0)
