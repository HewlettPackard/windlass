FROM alpine:3.5


ADD windlass.py /windlass.py

RUN apk --update add python3 docker git

RUN pip3 install pyyaml docker gitpython

VOLUME /sources
VOLUME /var/run/docker.sock

ENTRYPOINT ["/usr/bin/python3","/windlass.py"]
