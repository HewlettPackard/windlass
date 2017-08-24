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

import os


def load_proxy():
    proxy_keys = ('http_proxy', 'https_proxy', 'no_proxy')
    return {key: os.environ[key] for key in proxy_keys if key in os.environ}


def split_image(image):
    """Get the tag from a full image name.

    127.0.0.1:5000/image:latest => 127.0.0.1:5000/image, latest
    image:tag => image, tag
    """
    parts = image.split('/', 1)
    if len(parts) == 1 or (
            '.' not in parts[0] and
            ':' not in parts[0]):
        host, img = '', image
    else:
        host, img = parts

    if ':' in img:
        imagename, tag = img.rsplit(':', 1)
    else:
        imagename, tag = img, 'latest'

    if host:
        return host + "/" + imagename, tag
    return imagename, tag
