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

from requests import get
import testtools
from testtools.matchers import Equals


class Test_E2E(testtools.TestCase):
    def test_tags_in_registry(self):
        response = get('http://127.0.0.1:5000/v2/zing/windlass/tags/list')
        self.assertThat(response.status_code, Equals(200))
        self.assertThat(response.json()['name'], Equals('zing/windlass'))
