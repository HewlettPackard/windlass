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
set -x

SCRIPT_HOME=$(cd $(dirname $0); pwd)

# Use interactive mode if we can.
interactive=
test -t 0 && interactive=1

docker run --tty \
       ${interactive:+--interactive} \
       --volume /var/run/docker.sock:/var/run/docker.sock \
       --volume $PWD:$PWD \
       --workdir=$PWD \
       --env http_proxy --env https_proxy --env no_proxy \
       --env DOCKER_USER --env DOCKER_TOKEN \
       zing/windlass:latest $*
