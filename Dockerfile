FROM alpine:3.5

RUN set -e \
    && apk add --update --no-cache \
        ca-certificates \
        docker \
        git \
        python3 \
    ;

ENV PYTHON_DOCKER_VERSION 2.2.0
ENV PYTHON_GITPYTHON_VERSION 2.1.3
ENV PYTHON_PYYAML_VERSION 3.12
ENV GIT_SSL_NO_VERIFY=1
RUN set -e \
    && pip3 install --no-cache-dir \
        docker==${PYTHON_DOCKER_VERSION} \
        gitpython==${PYTHON_GITPYTHON_VERSION} \
        pyyaml==${PYTHON_PYYAML_VERSION} \
    ;

RUN set -e \
    && apk add --update --no-cache --virtual .download-deps \
        curl \

    && curl -fSsLO https://storage.googleapis.com/kubernetes-helm/helm-v2.2.0-linux-amd64.tar.gz \
    && tar xf helm-v2.2.0-linux-amd64.tar.gz linux-amd64/helm -C /usr/local/bin --strip-components 1 \
    && rm -f helm-v2.2.0-linux-amd64.tar.gz \

    && apk del .download-deps \

    && helm init -c \
    ;

ADD windlass.py /windlass.py

VOLUME /var/run/docker.sock

ENTRYPOINT ["/usr/bin/python3","/windlass.py"]
