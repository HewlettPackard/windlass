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

import windlass.charts
import windlass.images
import glob
import importlib
import logging
import os.path
import ruamel.yaml


class Pins(object):

    def __init__(self, config, parent={}):
        self.config = config
        self.parent = parent

    def get_value(self, key, default=None):
        return self.config.get(key, self.parent.get(key, default))

    @property
    def pins_dir(self):
        return self.get_value('pins_dir', 'pins')

    def get_pin_repo_file(self, repository):
        "Get name of pin file for this repository."
        return self.get_value(
            'repo_file',
            '{pins_dir}/{repository}.yaml').format(
                pins_dir=self.pins_dir,
                repository=repository)

    def get_pins_files_globs(self, repodir=None):
        globs = self.get_value('pins_files_globs', '{pins_dir}/*.yaml')
        if not isinstance(globs, list):
            globs = [globs]

        files_globs = [
            pin_files_glob.format(
                pins_dir=self.pins_dir)
            for pin_files_glob in globs]
        if repodir:
            files_globs = [
                os.path.join(repodir, files_glob)
                for files_glob in files_globs]
        return files_globs

    def iter_pin_files(self, repodir=None):
        pin_files_globs = self.get_pins_files_globs(repodir)
        pin_files_globs.reverse()

        for pin_files_glob in pin_files_globs:
            for pin_file in glob.glob(pin_files_glob):
                yield pin_file


class ImagePins(Pins):
    """Manage directory of files that pin docker images

    The format of the files is:

      images:
        imageorg/imagename: version
    """

    def __init__(self, config, parent=None):
        super().__init__(config, parent)
        self.key = self.config.get('key', 'images')

    def write_pins(self, artifacts, version, repository, repodir):
        pin_file = self.get_pin_repo_file(repository)
        full_pin_file = os.path.join(repodir, pin_file)

        preamble = ''
        try:
            data = ruamel.yaml.load(
                open(full_pin_file), Loader=ruamel.yaml.RoundTripLoader)
        except FileNotFoundError:
            basedir = os.path.dirname(full_pin_file)
            os.makedirs(basedir, exist_ok=True)
            data = {}
        else:
            # This is an edge case in ruamel.yaml. Here we have
            # a comment (like a copyright) but the yaml file is
            # empty. In that case data is None and so we just
            # write out the contents that are their already, and
            # treat this as a empty data.
            if data is None:
                preamble = open(full_pin_file).read()
                data = {}

        pins = data.get(self.key, {})
        for artifact in artifacts:
            if isinstance(artifact, windlass.images.Image):
                pins[artifact.name] = version
        data[self.key] = pins

        with open(full_pin_file, 'w') as fp:
            fp.write(preamble)
            ruamel.yaml.dump(data, fp, Dumper=ruamel.yaml.RoundTripDumper)

        return [pin_file]

    def read_pins(self, repodir=None):
        pins = []

        for pin_file in self.iter_pin_files(repodir):
            data = ruamel.yaml.safe_load(open(pin_file))
            if data:
                images = data.get(self.key, {})
                for image, version in images.items():
                    pins.append(
                        windlass.images.Image(dict(
                            name=image,
                            version=version)))

        return pins


class LandscapePins(Pins):
    """Read chart pins from landscaper files

    From a directory
    """

    def get_landscaper_file(self, repository, chartname, repodir=None):
        return self.get_value('landscape_file').format(
            pins_dir=self.pins_dir,
            repository=repository,
            chartname=chartname)

    def write_pins(self, artifacts, version, repository, repodir):
        written_files = []
        for artifact in artifacts:
            if not isinstance(artifact, windlass.charts.Chart):
                continue

            landscaper_file = self.get_landscaper_file(
                repository, artifact.name, repodir)

            try:
                data = ruamel.yaml.load(
                    open(os.path.join(repodir, landscaper_file)),
                    Loader=ruamel.yaml.RoundTripLoader)
            except FileNotFoundError:
                # Can we generate this file?
                raise RuntimeError(
                    'Landscape file %s does not exist.' % landscaper_file)

            chartname, chartversion = data['release']['chart'].split(':', 1)

            data['release']['chart'] = '%s:%s' % (chartname, version)
            data['release']['version'] = version

            with open(os.path.join(repodir, landscaper_file), 'w') as fp:
                ruamel.yaml.dump(data, fp, Dumper=ruamel.yaml.RoundTripDumper)

            written_files.append(landscaper_file)

        return written_files

    def read_pins(self, repodir=None):
        pins = []

        for pin_file in self.iter_pin_files(repodir):
            data = ruamel.yaml.safe_load(open(pin_file))
            release = data['release']
            chart = release['chart']
            chart, version = chart.split(':', 1)
            chart_version = release.get('version', version)
            if version != chart_version:
                raise RuntimeError(
                    'Conflicting chart version in file %s' % pin_file)

            helm_repo, chart_name = chart.split('/', 1)
            logging.debug('Chart comes from helm repo: %s' % helm_repo)

            pins.append(
                windlass.charts.Chart(dict(
                    name=chart_name,
                    version=version)))

        return pins


def import_class(class_string):
    """Returns class object specified by a string.

    https://stackoverflow.com/questions/452969/does-python-have-an-equivalent-to-java-class-forname # noqa

    Args:
        class_string: The string representing a class.

    Raises:
        ValueError if module part of the class is not specified.
    """
    module_name, _, class_name = class_string.rpartition('.')
    if module_name:
        mod = importlib.import_module(module_name)
        return getattr(mod, class_name)
    else:
        return globals()[class_name]


def parse_configuration(repodir=None):
    configuration = 'product-integration.yaml'
    if repodir:
        configuration = os.path.join(repodir, configuration)
    if not os.path.exists(configuration):
        raise RuntimeError('No configuration file')

    configuration_data = ruamel.yaml.load(
        open(configuration), Loader=ruamel.yaml.RoundTripLoader)

    for key, value in configuration_data.items():
        if isinstance(value, dict):
            if 'type' not in value:
                raise RuntimeError(
                    'type of collection unknown. please specify it')
            pintype = value['type']
            pinclass = import_class(pintype)
            pins = pinclass(configuration_data[key], configuration_data)
            yield pins


def write_pins(artifacts, version, repository, repodir=None):
    written_files = []
    for pins in parse_configuration(repodir):
        written_files.extend(
            pins.write_pins(artifacts, version, repository, repodir))
    return written_files


def read_pins(repodir=None):
    pins = []
    for reader in parse_configuration(repodir):
        pins.extend(reader.read_pins(repodir))

    return pins
