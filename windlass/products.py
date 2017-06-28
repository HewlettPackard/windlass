#!/bin/env python3
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

import yaml


def read_products(products_to_parse=[]):
    images = []
    charts = []
    for product_file in products_to_parse:
        with open(product_file, 'r') as f:
            product_def = yaml.load(f.read())

        if 'images' in product_def:
            for image_def in product_def['images']:
                images.append(image_def)
        if 'charts' in product_def:
            for chart_def in product_def['charts']:
                charts.append(chart_def)

    return images, charts
