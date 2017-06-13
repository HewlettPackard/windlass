#!/bin/bash
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

set -eu
set -o pipefail

# Pep8 checks
tox -epep8

# Build Windlass image
tox -ebuild

REGISTRY_CONTAINER=`docker run -d -p 5000:5000 registry:2`
SOURCES_DIR="$(cd ..; pwd)"
docker run --rm -t -e http_proxy -e https_proxy \
       -v  ${SOURCES_DIR}:${SOURCES_DIR} \
       -v /var/run/docker.sock:/var/run/docker.sock \
       zing/windlass:latest --debug --directory ${PWD} \
       --repository 127.0.0.1:5000 dev

tox -etests -- tests.test_e2e.\*

docker kill $REGISTRY_CONTAINER
docker rm $REGISTRY_CONTAINER
