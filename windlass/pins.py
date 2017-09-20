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
import os.path
import ruamel.yaml


class Pins(object):

    # Type specific defaults. Different for each subclass
    # default_pin_file
    # default_pins_files_globs

    def __init__(self, config, parent={}):
        self.config = config
        self.parent = parent

    def get_value(self, key, default=None):
        return self.config.get(key, self.parent.get(key, default))

    @property
    def pins_dir(self):
        return self.get_value('pins_dir', 'pins')

    def get_pin_file(self, repository, **kwargs):
        "Get name of pin file for this repository."
        return self.get_value(
            'pin_file',
            self.default_pin_file).format(
                pins_dir=self.pins_dir,
                repository=repository,
                **kwargs)

    def get_pins_files_globs(self, repodir=None):
        globs = self.get_value(
            'pins_files_globs', self.default_pins_files_globs)
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

    default_pin_file = '{pins_dir}/{repository}.yaml'
    default_pins_files_globs = '{pins_dir}/**/*.yaml'

    def __init__(self, config, parent=None):
        super().__init__(config, parent)
        self.key = self.config.get('key', 'images')

    def write_pins(self, artifacts, version, repository, repodir):
        pin_file = self.get_pin_file(repository)
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
        pins_set = False
        for artifact in artifacts:
            if isinstance(artifact, windlass.images.Image):
                current_pins = pins.get(artifact.imagename, None)
                if not isinstance(current_pins, dict):
                    pins[artifact.imagename] = current_pins = {}
                current_pins['version'] = version
                if artifact.devtag != current_pins.get('devtag', 'latest'):
                    current_pins['devtag'] = artifact.devtag
                pins_set = True

        if not pins_set:
            return []

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
                    if isinstance(version, dict):
                        pins.append(
                            windlass.images.Image(dict(
                                name=image,
                                **version)))
                    else:
                        pins.append(
                            windlass.images.Image(dict(
                                name=image,
                                version=version)))

        return pins


class LandscapePins(Pins):
    """Read chart pins from landscaper files

    From a directory
    """

    default_pin_file = '{pins_dir}/{name}.yaml'
    default_pins_files_globs = '{pins_dir}/*.yaml'

    def write_pins(self, artifacts, version, repository, repodir):
        written_files = []
        for artifact in artifacts:
            if not isinstance(artifact, windlass.charts.Chart):
                continue

            pin_file = self.get_pin_file(repository, name=artifact.name)
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

            # chartname may contain the name of the helm repository to find
            # this artifact in.
            if data and data.get('release', {}).get('chart', None) is not None:
                chartname, _version = data['release']['chart'].split(':', 1)
            else:
                chartname = artifact.name

            if data.get('name', None) is None:
                data['name'] = artifact.name

            if data.get('release', None) is None:
                data['release'] = {}

            data['release']['chart'] = '%s:%s' % (chartname, version)
            data['release']['version'] = version

            with open(full_pin_file, 'w') as fp:
                fp.write(preamble)
                ruamel.yaml.dump(data, fp, Dumper=ruamel.yaml.RoundTripDumper)

            written_files.append(pin_file)

        return written_files

    def read_pins(self, repodir=None):
        pins = []

        for pin_file in self.iter_pin_files(repodir):
            data = ruamel.yaml.safe_load(open(pin_file))
            release = data and data.get('release', None)
            if not release:
                continue
            chart = release['chart']
            chart, version = chart.split(':', 1)
            chart_version = release.get('version', version)
            if version != chart_version:
                raise RuntimeError(
                    'Conflicting chart version in file %s' % pin_file)

            chart_name = chart.split('/', 1)[-1]

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

    configuration_pins = configuration_data.get('pins', {})
    for key, value in configuration_pins.items():
        if isinstance(value, dict):
            if 'type' not in value:
                raise RuntimeError(
                    'type of collection unknown. please specify it')
            pintype = value['type']
            pinclass = import_class(pintype)
            pins = pinclass(configuration_pins[key], configuration_pins)
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
