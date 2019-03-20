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

import fnmatch
import windlass.charts
import windlass.generic
import windlass.images
import windlass.tools
import git
import glob
import importlib
import jinja2
import logging
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
        if repodir and not isinstance(repodir, git.Commit):
            files_globs = [
                os.path.join(repodir, files_glob)
                for files_glob in files_globs]
        return files_globs

    def iter_pin_files(self, repodir=None):
        pin_files_globs = self.get_pins_files_globs(repodir)
        pin_files_globs.reverse
        if isinstance(repodir, git.Commit):
            fnlist = [i for i in windlass.tools.all_blob_names(repodir.tree)]
            for pin_files_glob in pin_files_globs:
                for blob_name in fnmatch.filter(fnlist, pin_files_glob):
                    yield (repodir.tree / blob_name).data_stream
        else:
            for pin_files_glob in pin_files_globs:
                for pin_file in glob.glob(pin_files_glob):
                    yield open(pin_file)

    def iter_artifacts(self, artifacts, artifacttype=None):
        ignore = self.config.get('ignore', [])
        only = self.config.get('only', [])
        if ignore and only:
            raise Exception(
                "Cannot specifiy 'only' and 'ignore' for %s" % (
                    self.name))

        for artifact in artifacts:
            if artifacttype is not None \
               and not isinstance(artifact, artifacttype):
                logging.debug('Skipping artifact of wrong type %s (%s)' % (
                    artifact.name, artifacttype))
                continue

            if artifact.name in ignore:
                logging.debug('Skipping ignored artifact %s' % artifact.name)
                continue

            if only and artifact.name not in only:
                continue

            yield artifact


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

    def write_pins(self, artifacts, repository, repodir=None, metadata=None):
        pin_file = self.get_pin_file(repository)
        if repodir:
            full_pin_file = os.path.join(repodir, pin_file)
        else:
            full_pin_file = pin_file

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
        for artifact in self.iter_artifacts(
                artifacts, artifacttype=windlass.images.Image):
            current_pins = pins.get(artifact.imagename, None)

            if not isinstance(current_pins, dict):
                pins[artifact.imagename] = current_pins = {}
            current_pins['version'] = artifact.version
            if artifact.devtag != current_pins.get('devtag', 'latest'):
                current_pins['devtag'] = artifact.devtag

            # Update metadata
            if metadata is not None:
                if 'zing-metadata' not in current_pins:
                    current_pins['zing-metadata'] = {}
                current_pins['zing-metadata'].update(metadata)

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

        ignore = self.config.get('ignore', [])

        for pin_stream in self.iter_pin_files(repodir):
            data = ruamel.yaml.safe_load(pin_stream)
            if data:
                images = data.get(self.key, {})
                for image, version in images.items():
                    if image in ignore:
                        logging.debug('Ignoring image %s for reading' % image)
                        continue
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

    def write_pins(self, artifacts, repository, repodir=None, metadata=None):
        written_files = []
        for artifact in self.iter_artifacts(
                artifacts, artifacttype=windlass.charts.Chart):
            pin_file = self.get_pin_file(repository, name=artifact.name)
            if repodir:
                full_pin_file = os.path.join(repodir, pin_file)
            else:
                full_pin_file = pin_file

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

            data['release']['chart'] = '%s:%s' % (chartname, artifact.version)

            # Store metadata here.
            if metadata is not None:
                if 'zing-metadata' not in data:
                    data['zing-metadata'] = {}
                data['zing-metadata'].update(metadata)

            with open(full_pin_file, 'w') as fp:
                fp.write(preamble)
                ruamel.yaml.dump(data, fp, Dumper=ruamel.yaml.RoundTripDumper)

            written_files.append(pin_file)
        return written_files

    def read_pins(self, repodir=None):
        pins = []

        ignore = self.config.get('ignore', [])

        for pin_stream in self.iter_pin_files(repodir):
            data = ruamel.yaml.safe_load(pin_stream)
            release = data and data.get('release', None)
            if not release:
                continue
            metadata = data.get('zing-metadata')
            chart = release['chart']
            chart, version = chart.split(':', 1)
            chart_name = chart.split('/', 1)[-1]

            if chart_name in ignore:
                logging.debug('Ignoring chart %s for reading' % chart_name)
                continue

            pins.append(
                windlass.charts.Chart(data={
                    'name': chart_name,
                    'version': version,
                    'zing-metadata': metadata
                }))

        return pins


class GenericPins(Pins):
    """Manage directory of files that pin docker images

    The format of the files is:

      generic:
        {artifactname}:
            version: {version}
            filename: {filename}
    """

    default_pin_file = '{pins_dir}/{repository}.yaml'
    default_pins_files_globs = '{pins_dir}/**/*.yaml'

    def __init__(self, config, parent=None):
        super().__init__(config, parent)
        self.key = self.config.get('key', 'generic')

    def write_pins(self, artifacts, repository, repodir=None, metadata=None):
        pin_file = self.get_pin_file(repository)
        if repodir:
            full_pin_file = os.path.join(repodir, pin_file)
        else:
            full_pin_file = pin_file

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
        for artifact in self.iter_artifacts(
                artifacts, artifacttype=windlass.generic.Generic):
            current_pins = pins.get(artifact.name, {})

            current_pins['version'] = artifact.version
            current_pins['filename'] = artifact.get_filename()

            # Update metadata
            if metadata is not None:
                if 'zing-metadata' not in current_pins:
                    current_pins['zing-metadata'] = {}
                current_pins['zing-metadata'].update(metadata)

            pins_set = True
            pins[artifact.name] = current_pins

        if not pins_set:
            return []

        data[self.key] = pins

        with open(full_pin_file, 'w') as fp:
            fp.write(preamble)
            ruamel.yaml.dump(data, fp, Dumper=ruamel.yaml.RoundTripDumper)

        return [pin_file]

    def read_pins(self, repodir=None):
        pins = []

        ignore = self.config.get('ignore', [])

        for pin_stream in self.iter_pin_files(repodir):
            data = ruamel.yaml.safe_load(pin_stream)
            if data:
                artifacts = data.get(self.key, {})
                # content is dictionary with version and filename
                for artifact, content in artifacts.items():
                    if artifact in ignore:
                        logging.debug(
                            'Ignoring generic artifact %s for reading' % (
                                artifact))
                        continue
                    # Get the actual filename as recorded in the metadata
                    filename = content.pop('filename', None)
                    pins.append(
                        windlass.generic.Generic(
                            dict(name=artifact,
                                 **content),
                            actual_filename=filename,
                        )
                    )
        return pins


class OverrideYamlConfiguration(object):

    def __init__(self, config, parent=None):
        self.config = config
        self.parent = parent

    def write_pins(self, artifacts, repository, repodir=None, metadata=None):
        """See windlass/tests/integrationrepo-override/products-integation.yaml

        Write out yaml configuration based on the documentation in README.md
        """
        yaml = ruamel.yaml.YAML()
        updated = []
        for override, override_config in self.config.items():
            if override == 'type':
                continue

            conf_file = override_config['file']
            if repodir:
                full_conf_file = os.path.join(repodir, conf_file)
            else:
                full_conf_file = conf_file
            artifacttype = import_class(override_config['artifacttype'])

            filtered_artifacts = {}
            for artifact in artifacts:
                if isinstance(artifact, artifacttype):
                    filtered_artifacts[artifact.name] = artifact

            preamble = ''
            try:
                data = yaml.load(open(full_conf_file))
            except FileNotFoundError:
                basedir = os.path.dirname(full_conf_file)
                os.makedirs(basedir, exist_ok=True)
                data = {}
            else:
                # This is an edge case in ruamel.yaml. Here we have
                # a comment (like a copyright) but the yaml file is
                # empty. In that case data is None and so we just
                # write out the contents that are their already, and
                # treat this as a empty data.
                if data is None:
                    preamble = open(full_conf_file).read()
                    data = {}

            updatedfile = False
            values = override_config['values']
            for conf in values:
                yamlpath = conf['yamlpath']
                valuetemplate = conf['value']
                try:
                    value = jinja2.Template(valuetemplate).render(
                        artifacts=filtered_artifacts)
                except jinja2.exceptions.UndefinedError as e:
                    logging.debug(
                        "Undefined error '%s' rendering '%s', skipping." % (
                            e.message, valuetemplate))
                    continue

                yamlpathlist = yamlpath.split('.')
                conffield = yamlpathlist.pop()

                subdata = data
                for path in yamlpathlist:
                    subdata = subdata[path]

                changed = subdata.get(conffield, object()) != value

                subdata[conffield] = value

                if changed:
                    updatedfile = True
                    subdata.yaml_add_eol_comment(
                        'This value is generated automatically by: %s' % (
                            repository),
                        conffield)

            if updatedfile:
                with open(full_conf_file, 'w') as fp:
                    fp.write(preamble)
                    yaml.dump(data, fp)

                updated.append(conf_file)

        return updated

    def read_pins(self, repodir=None):
        """From configuration read the pins and return set of artifacts

        Some artifacts - like generic need to know the filename? attirbute
        is we can't deduce from the override mechanism an Generic artifact
        object that will work with the rest of the promotion. This will
        require a fix to generics.

        Instead assume that we will be using the corresponding GenericPins,
        ImagePins or LandscaperPins in conjuction to the OverridePins
        so that the artifacts are pushed to the correct repositories.
        """
        return []

#        pins = []
#        yaml = ruamel.yaml.YAML()
#        for override, override_config in self.config.items():
#            if override == 'type':
#                continue

#            full_conf_file = override_config['file']
#            if repodir:
#                full_conf_file = os.path.join(repodir, full_conf_file)
#            artifacttype = import_class(override_config['artifacttype'])

#            data = yaml.load(open(full_conf_file))

#            value = override_config['value']
#            for conf in value:
#                yamlpath = conf['yamlpath']
#                artifact = conf['version']

#                subdata = data
#                for path in yamlpath.split('.'):
#                    subdata = subdata[path]

#                pins.append(artifacttype(dict(
#                    name=artifact,
#                    version=subdata)))

#        return pins


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


def read_configuration(repodir=None):
    configuration = 'product-integration.yaml'
    if isinstance(repodir, git.Commit):
        if configuration in repodir.tree:
            stream = (repodir.tree/configuration).data_stream
        else:
            return {}
    else:
        if repodir:
            configuration = os.path.join(repodir, configuration)
            if not os.path.exists(configuration):
                return {}
        stream = open(configuration)
    configuration_data = ruamel.yaml.load(
        stream, Loader=ruamel.yaml.RoundTripLoader)

    return configuration_data


def parse_configuration_pins(repodir=None):
    configuration_data = read_configuration(repodir)
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


def write_pins(artifacts, repository, repodir=None, metadata=None):
    written_files = []
    for pins in parse_configuration_pins(repodir):
        written_files.extend(
            pins.write_pins(artifacts, repository, repodir, metadata))
    return written_files


def read_pins(repodir=None):
    pins = []
    for reader in parse_configuration_pins(repodir):
        pins.extend(reader.read_pins(repodir))
    return pins


def diff_pins_dir(lhs_repo_dir, rhs_repo_dir, metadata=False):
    lhs_pins = read_pins(lhs_repo_dir)
    rhs_pins = read_pins(rhs_repo_dir)
    return diff_pins(lhs_pins, rhs_pins, metadata=metadata)


def diff_pins(lhs_pins, rhs_pins, metadata=False):

    def changed_metadata(lh, rh):
        return metadata and (
            lh.data.get('zing-metadata', {}) !=
            rh.data.get('zing-metadata', {})
        )

    diff_pins = []
    # Check for pins changes betweeen lhs and rhs
    diff_pins.extend([
        dict(
            name=rh.name,
            lhs=lh,
            rhs=rh
        ) for rh in rhs_pins for lh in lhs_pins
        if rh.name == lh.name and (
            rh.version != lh.version or changed_metadata(lh, rh)
        )
    ])

    # Check for pins in rhs but not in lhs
    for rh in rhs_pins:
        if not any(lh.name == rh.name for lh in lhs_pins):
            diff_pins.append(dict(
                name=rh.name,
                lhs=None,
                rhs=rh,
            ))

    # Check for pins in lhs but not in rhs
    for lh in lhs_pins:
        if not any(rh.name == lh.name for rh in rhs_pins):
            diff_pins.append(dict(
                name=lh.name,
                lhs=lh,
                rhs=None
            ))

    return diff_pins
