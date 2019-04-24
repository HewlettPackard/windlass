#
# (c) Copyright 2017-2019 Hewlett Packard Enterprise Development LP
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

FROM alpine:3.9.3 as base

RUN set -e \
    && apk add --update --no-cache \
        ca-certificates \
        docker \
        git \
        python3 \
    ;

FROM base as build
RUN set -e \
    # Install development libraries for pip3 install later
    && apk add --update --no-cache --virtual .build-deps \
        python3-dev \
        gcc \
        musl-dev \
    ;

ENV GIT_SSL_NO_VERIFY=

RUN set -e \
    && apk add --update --no-cache \
        curl \
    && curl -fSsLO https://storage.googleapis.com/kubernetes-helm/helm-v2.2.0-linux-amd64.tar.gz \
    && tar xf helm-v2.2.0-linux-amd64.tar.gz linux-amd64/helm -C /usr/local/bin --strip-components 1 \
    ;

ADD . /tmp/package

RUN set -e \
    && pip3 install --prefix /usr/local --no-cache-dir /tmp/package \
    ;

FROM base

ENV PYTHONPATH=/usr/local/lib/python3.6/site-packages
COPY --from=build /usr/local /usr/local

RUN set -e \
    && helm init -c \
    ;

VOLUME /var/run/docker.sock

ENTRYPOINT ["windlass"]
