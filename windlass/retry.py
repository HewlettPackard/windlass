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
import urllib3.exceptions

import windlass.exc


class simple(object):
    """Retry decorator

    Add this decorator to any method that we need to retry.
    """

    def __init__(self, max_retries=3, retry_backoff=5):
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    def __call__(self, func):
        attempts = []

        @functools.wraps(func)
        def retry_f(*args, **kwargs):
            artifact = args[0]
            for i in range(0, self.max_retries):
                try:
                    return func(*args, **kwargs)
                except (urllib3.exceptions.ReadTimeoutError,
                        windlass.exc.RetryableFailure) as e:
                    logging.exception(
                        '%s: problem occuried retrying, backing '
                        'off %d seconds' % (
                            artifact.name, self.retry_backoff))
                    attempts.append(e)
                    time.sleep(self.retry_backoff)

            raise windlass.exc.FailedRetriesException(
                '%s: Maximum number of retries occurred (%d)' % (
                    artifact.name, self.max_retries),
                attempts=attempts)

        return retry_f
