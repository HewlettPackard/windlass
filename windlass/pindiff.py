#!/usr/bin/env python3
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
from argparse import ArgumentParser

from git import Repo
from prettytable import PrettyTable

from windlass.pins import diff_pins_dir


def main():
    parser = ArgumentParser()
    parser.add_argument('--repository', type=str, default='.')
    parser.add_argument(
        '--check-metadata',
        action='store_true',
        help='Check for metadata changes as well as version changes')
    parser.add_argument('first_commit')
    parser.add_argument('second_commit')
    ns = parser.parse_args()
    r = Repo(ns.repository)
    table = PrettyTable(field_names=[
        'Artifact name',
        'Version in first commit',
        'Version in second commit'])
    for d in diff_pins_dir(
        r.commit(ns.first_commit),
        r.commit(ns.second_commit),
        metadata=ns.check_metadata
    ):
        table.add_row([
            d['name'],
            d['lhs'].version if d['lhs'] else 'Not included',
            d['rhs'].version if d['rhs'] else 'Not included'
            ])

    print(table.get_string())


if __name__ == '__main__':
    main()
