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


class WindlassException(Exception):
    "Exception to be parent of all Windlass exceptions"
    def __init__(self, *args, **kwargs):
        # Exception does not take kwargs, but should inheritance change we
        # might need to pass it.
        super().__init__(*args)


class WindlassExternalException(WindlassException):
    """Exception to catch problems with processes outside of windlass

    This exception is to be used to catch problems that most likely are
    not issues with windlass, but problems arising from issues like bad
    build data, failure to upload items.
    """
    def __init__(self, *args, **kwargs):
        self.out = kwargs.pop('out', None)
        self.errors = kwargs.pop('errors', None)
        self.artifact_name = kwargs.pop('artifact_name', None)
        self.debug_data = kwargs.pop('debug_data', None)
        super().__init__(*args, **kwargs)


class RetryableFailure(WindlassExternalException):
    """Rasise this exception when you want to retry the task

    This will retry and task a fix number of time with a small
    time back off.
    """


class FailedRetriesException(WindlassException):
    """Raise this exception when multiple retries failed.

    It requires keyword argument attempts containing list of exceptions from
    failed attempts.
    """
    def __init__(self, *args, **kwargs):
        self.attempts = kwargs.pop('attempts')
        super().__init__(*args, **kwargs)


class WindlassBuildException(WindlassExternalException):
    "Exception to catch failures to build artifacts"

    def debug_message(self):
        'Returns a long debug output.'
        msg = '%s: Build failed with output:\n' % self.artifact_name
        for line in self.out:
            msg += '%s: %s\n' % (
                self.artifact_name,
                line)
        if self.errors:
            msg += '%s: Error output:\n' % self.artifact_name
            for line in self.errors:
                msg += '%s: %s\n' % (
                    self.artifact_name,
                    line)
        msg += '%s: Arguments passed to docker:\n' % self.artifact_name
        for k, v in self.debug_data.items():
            msg += '%s: %s=%s\n' % (self.artifact_name, k, v)
        return msg


class WindlassPushPullException(RetryableFailure):
    "Exception to catch failures to upload or download artifacts"
    pass
