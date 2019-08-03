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

import functools
import logging
import time
import traceback
import types
import urllib3.exceptions

import windlass.exc


def simple_debug_message(self):
    return self._debug_message


def ensure_debug_message(excobj):
    if not hasattr(excobj, 'debug_message'):

        excobj._debug_message = (
            'Exception traceback:\n%s' % traceback.format_exc())
        # Bind method to instance
        excobj.debug_message = types.MethodType(simple_debug_message, excobj)
    return excobj


class simple(object):
    """Retry decorator

    Add this decorator to any method that we need to retry.
    """

    def __init__(self, max_retries=3, retry_backoff=5, retry_on=None):
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

        self.retry_on = {
            urllib3.exceptions.ReadTimeoutError,
            windlass.exc.RetryableFailure,
        }
        if retry_on:
            self.retry_on.update(retry_on)

    def __call__(self, func):
        attempts = []

        @functools.wraps(func)
        def retry_f(*args, **kwargs):
            try:
                name = args[0].name
            except (AttributeError, IndexError):
                name = func

            for i in range(0, self.max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if not any(isinstance(e, r) for r in self.retry_on):
                        raise
                    logging.info(
                        '%s: problem occurred retrying, backing '
                        'off %d seconds' % (
                            name, self.retry_backoff))
                    attempts.append(ensure_debug_message(e))
                    time.sleep(self.retry_backoff)
                # failure from nested retry, don't retry again
                except windlass.exc.FailedRetriesException as e:
                    # catch and re-raise with name for nested retry
                    e.args[0] = ('%s: ' + e.args[0]) % name
                    raise e
            logging.error(
                '%s: Maximum number of retries occurred (%d), details will be'
                ' displayed at the end' % (
                    name, self.max_retries),
                )
            raise windlass.exc.FailedRetriesException(
                '%s: Maximum number of retries occurred (%d)' % (
                    name, self.max_retries),
                attempts=attempts)

        return retry_f
