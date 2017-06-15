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

FROM alpine:3.5

RUN set -e \
    && apk add --update --no-cache \
        ca-certificates \
        docker \
        git \
        python3 \
    ;

ENV GIT_SSL_NO_VERIFY=

RUN set -e \
    && apk add --update --no-cache --virtual .download-deps \
        curl \

    && curl -fSsLO https://storage.googleapis.com/kubernetes-helm/helm-v2.2.0-linux-amd64.tar.gz \
    && tar xf helm-v2.2.0-linux-amd64.tar.gz linux-amd64/helm -C /usr/local/bin --strip-components 1 \
    && rm -f helm-v2.2.0-linux-amd64.tar.gz \

    && apk del .download-deps \

    && helm init -c \
    ;

# This needs to correspond to Version field in METADATA
ENV GATHER_VERSION=0.1.0

COPY dist/windlass-${GATHER_VERSION}-py3-none-any.whl /

RUN set -e \
    && pip3 install --no-cache-dir \
       windlass-${GATHER_VERSION}-py3-none-any.whl \
    ;

VOLUME /var/run/docker.sock

ENTRYPOINT ["windlass"]
