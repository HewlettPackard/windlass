FROM alpine:3.5

RUN apk --update add python3 docker git wget ca-certificates

RUN pip3 install pyyaml docker gitpython

RUN wget https://storage.googleapis.com/kubernetes-helm/helm-v2.2.0-linux-amd64.tar.gz && \
    tar xf helm-v2.2.0-linux-amd64.tar.gz linux-amd64/helm && \
    mv linux-amd64/helm /usr/local/bin

RUN helm init -c

ADD windlass.py /windlass.py

VOLUME /sources
VOLUME /var/run/docker.sock

ENTRYPOINT ["/usr/bin/python3","/windlass.py"]
