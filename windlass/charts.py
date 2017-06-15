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

from windlass.tools import guess_repo_name
from git import Repo
import hashlib
import logging
import os
import subprocess
from tempfile import TemporaryDirectory


def fetch_remote_chart(repo, chart, version, output_dir):
    repo_name = hashlib.sha1(repo.encode('utf-8')).hexdigest()[:20]
    subprocess.call(['helm', 'repo', 'add', repo_name, repo])

    if version:
        version_args = ['--version', version]
    else:
        version_args = []

    subprocess.call(['helm', 'fetch', repo_name+'/'+chart, '-d', output_dir] +
                    version_args)


def package_local_chart(directory, chart, repodir, chartdir):
    subprocess.call(
        ['helm', 'package',
         os.path.abspath(os.path.join(".", repodir, directory, chart))],
        cwd=chartdir)


def process_chart(chart_def, ns):

    chart = chart_def['name']
    if 'repo' in chart_def:
        package_chart(chart_def, ns.repodir, ns.charts_directory)
    elif 'remote' in chart_def:
        version = chart_def['version']
        repository = chart_def['remote']
        fetch_remote_chart(repository, chart, version, ns.charts_directory)
    else:
        errmsg = ('Chart %s has no git or helm repo defined '
                  'and cannot be processed' % chart)
        logging.error(errmsg)
        raise Exception(errmsg)


def package_chart(chart_def, repodir, chartdir):

    if chart_def['repo'] == '.':
        repopath = '.'
    else:
        repopath = guess_repo_name(chart_def['repo'])

    if os.path.exists(repopath):
        logging.info('%s: Packaging chart from local directory %s'
                     % (chart_def['name'], repopath))
        package_local_chart(os.path.join(repopath, chart_def['location']),
                            chart_def['name'], repodir, chartdir)
    else:
        with TemporaryDirectory() as tempdir:
            branch = chart_def.get('branch', 'master')
            logging.info('%s: Packaging chart from git repository %s branch %s'
                         % (chart_def['name'], chart_def['repo'], branch))
            Repo.clone_from(chart_def['repo'],
                            tempdir,
                            branch=branch,
                            depth=1,
                            single_branch=True)
            package_local_chart(os.path.join(tempdir, chart_def['location']),
                                chart_def['name'],
                                repodir,
                                chartdir)
