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

ARG HELM_VERSION=v3.5.4

FROM alpine:3.16.2 as base

RUN set -e \
    && apk add --update --no-cache \
        ca-certificates \
        docker \
        git \
        python3 \
        py3-pip \
        py3-setuptools \
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

ARG HELM_VERSION
RUN set -e \
    && apk add --update --no-cache \
        curl \
    && curl -fSsLO https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz \
    && tar xf helm-${HELM_VERSION}-linux-amd64.tar.gz linux-amd64/helm -C /usr/local/bin --strip-components 1 \
    ;

ADD . /tmp/package

RUN set -e \
    && python3 -m pip install --upgrade setuptools \
    && python3 -m pip install --prefix /usr/local --no-cache-dir /tmp/package \
    ;

FROM base

# Recent git will complain if running as a different user to the owner of the repo
RUN git config --global --add safe.directory '*'
ENV PYTHONPATH=/usr/local/lib/python3.10/site-packages
COPY --from=build /usr/local /usr/local

VOLUME /var/run/docker.sock

ENTRYPOINT ["windlass"]
