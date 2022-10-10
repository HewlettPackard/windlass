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
# Until PEP8 would become seprate test job this should permit running multiple
# tests at same time.


from flake8 import api
from io import StringIO
import sys
import testtools
from testtools.matchers import Never


class Test_Style(testtools.TestCase):
    def test_flake8(self):
        try:
            oldout = sys.stdout
            sys.stdout = StringIO()
            style_guide = api.get_style_guide(exclude=['build'])
            report = style_guide.check_files('.')
            if report.total_errors > 0:
                for line in sys.stdout.getvalue().split('\n'):
                    if line:
                        self.expectThat('', Never(), line)
        finally:
            sys.stdout = oldout
