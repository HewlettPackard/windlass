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


class WindlassExternalException(Exception):
    """Exception to catch problems with processes outside of windlass

    This exception is to be used to catch problems that most likely are
    not issues with windlass, but problems arising from issues like bad
    build data, failure to upload items.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.out = kwargs.get('out')
        self.errors = kwargs.get('errors')
        self.artifact_name = kwargs.get('artifact_name')
        self.debug_data = kwargs.get('debug_data')


class RetryableFailure(WindlassExternalException):
    """Rasise this exception when you want to retry the task

    This will retry and task a fix number of time with a small
    time back off.
    """


class WindlassBuildException(WindlassExternalException):
    "Exception to catch failures to build artifacts"
    pass


class WindlassPushPullException(RetryableFailure):
    "Exception to catch failures to upload or download artifacts"
    pass
