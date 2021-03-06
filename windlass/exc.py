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

# All exception MUST not have any required arguments to __init__ otherwise
# when pickled they will hit Python bug:
# https://bugs.python.org/issue32696


class WindlassException(Exception):
    "Exception to be parent of all Windlass exceptions"
    def __init__(self, *args, **kwargs):
        # Exception does not take kwargs, but should inheritance change we
        # might need to pass it.
        super().__init__(*args)

    def debug_message(self):
        raise NotImplemented()


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


class MissingArtifact(WindlassExternalException):
    """Exception raised when artifact is missing.

    Raise when windlass opration on artifact does not find artifact in expected
    place.
    """
    def debug_message(self):
        msg = '%s: failed to find artifact\n' % self.artifact_name
        for line in self.errors:
            msg += '%s: %s' % (self.artifact_name, line)
        return msg


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
        self.attempts = kwargs.pop('attempts', None)
        super().__init__(*args, **kwargs)

    def debug_message(self):
        msg = 'Failed %d attempts:\n' % len(self.attempts)
        for index, attempt in enumerate(self.attempts):
            msg += 'Attempt #%d:\n%s\n' % (index, attempt.debug_message())
        return msg


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
    def debug_message(self):
        msg = 'Error pushing or pulling artifact:\n'
        msg += '\n'.join(self.errors)
        msg += '\n'
        msg += 'Output:\n'
        for line in self.out:
            msg += line + '\n'
        msg += 'End of output.'
        return msg


class MissingEntryInChartValues(WindlassException):
    def __init__(self, *args, **kwargs):
        self.missing_key = kwargs.pop('missing_key', None)
        source_dict = kwargs.pop('expected_source', None)
        if source_dict:
            self.expected_path = []
            self._dict_to_path(source_dict)
        self.chart_name = kwargs.pop('chart_name', None)
        self.values_filename = kwargs.pop('values_filename', None)
        super().__init__(*args, **kwargs)

    def _dict_to_path(self, values_dict):
        key = list(values_dict)[0]
        self.expected_path.append(key)
        if isinstance(values_dict[key], dict):
            self._dict_to_path(values_dict[key])

    def __str__(self):
        return (
            'Failed to repackage chart %s, as key %s was not found in file '
            '%s at expected level.' % (
                self.chart_name,
                self.missing_key,
                self.values_filename
            ))

    def debug_message(self):
        msg = 'Failed to repackage chart %s.\n' % self.chart_name
        msg += ('It was expected that values.yaml(%s) would contain dict of '
                'following structure:\n' % self.values_filename)
        for i, key in enumerate(self.expected_path):
            msg += i * 2 * ' ' + '%s:\n' % key
        msg += ('Key "%s" was not where expected, you need to correct '
                'values.yaml to contain such structure, or change your '
                'artifacts.yaml to "values" entry for %s to structure '
                'that matches one in values.yaml' % (
                    self.missing_key, self.chart_name))
        return msg
