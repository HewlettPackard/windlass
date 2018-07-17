#
# (c) Copyright 2017-2018 Hewlett Packard Enterprise Development LP
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

import docker
import windlass.api
import windlass.exc
import windlass.tools
from git import Repo
import logging
import multiprocessing
import os

import yaml


def check_docker_stream(stream):
    # Read output from docker command and raise exception
    # if docker hit an error processing the command.
    # Also log messages if debugging is turned on.
    name = multiprocessing.current_process().name
    last_msgs = []
    for line in stream:
        if not line:
            continue

        data = yaml.load(line)
        if 'status' in data:
            if 'id' in data:
                msg = '%s layer %s: %s' % (name,
                                           data['id'],
                                           data['status'])
            else:
                msg = '%s: %s' % (name, data['status'])
            if msg not in last_msgs:
                logging.debug(msg)
                last_msgs.append(msg)
        if 'error' in data:
            logging.error("Error processing image %s:%s" % (
                name, data['error']))
            raise windlass.exc.WindlassPushPullException(
                '%s ERROR from docker: %s' % (
                    name, data['error']
                ),
                out=last_msgs,
                errors=[data['error']],
            )


def push_image(imagename, push_tag='latest', auth_config=None):
    client = docker.from_env(
        version='auto',
        timeout=180)
    name = multiprocessing.current_process().name
    logging.info('%s: Pushing as %s:%s', name, imagename, push_tag)

    output = client.images.push(
        imagename, push_tag, auth_config=auth_config,
        stream=True)
    check_docker_stream(output)
    return True


def clean_tag(tag):
    clean = ''
    valid = ['_', '-', '.']
    for c in tag:
        if c.isalnum() or c in valid:
            clean += c
        else:
            clean += '_'
    return clean[:128]


def build_verbosly(name, path, nocache=False, dockerfile=None,
                   pull=True):
    client = docker.from_env(
        version='auto',
        timeout=180)
    bargs = windlass.tools.load_proxy()
    logging.info("Building %s from path %s", name, path)
    stream = client.api.build(path=path,
                              tag=name,
                              nocache=nocache,
                              buildargs=bargs,
                              dockerfile=dockerfile,
                              pull=pull)
    errors = []
    output = []
    for line in stream:
        data = yaml.load(line.decode())
        if 'stream' in data:
            for out in data['stream'].split('\n\r'):
                logging.debug('%s: %s', name, out.strip())
                # capture detailed output in case of error
                output.append(out.strip())
        elif 'error' in data:
            errors.append(data['error'])
    if errors:
        logging.error(
            'Failed to build %s. Error details will be shown at the end.',
            name)
        debug_data = {'buildargs.%s' % k: v for k, v in bargs.items()}
        debug_data['dockerfile'] = dockerfile
        debug_data['tag'] = name
        debug_data['path'] = path
        debug_data['nocache'] = str(nocache)
        debug_data['pull'] = str(pull)
        raise windlass.exc.WindlassBuildException(
            "Failed to build {}".format(name),
            out=output,
            errors=errors,
            artifact_name=name,
            debug_data=debug_data)
    logging.info("Successfully built %s from path %s", name, path)
    return client.images.get(name)


def build_image_from_local_repo(repopath, imagepath, name, tags=[],
                                nocache=False, dockerfile=None, pull=True):
    logging.info('%s: Building image from local directory %s',
                 name, os.path.join(repopath, imagepath))
    repo = Repo(repopath)
    image = build_verbosly(name,
                           os.path.join(repopath, imagepath),
                           nocache=nocache,
                           dockerfile=dockerfile,
                           pull=pull)
    if repo.head.is_detached:
        commit = repo.head.commit.hexsha
    else:
        commit = repo.active_branch.commit.hexsha
        image.tag(name,
                  clean_tag('branch_' +
                            repo.active_branch.name.replace('/', '_')))
    if repo.is_dirty():
        image.tag(name,
                  clean_tag('last_ref_' + commit))
    else:
        image.tag(name, clean_tag('ref_' + commit))

    return image


@windlass.api.register_type('images')
class Image(windlass.api.Artifact):

    def __init__(self, data):
        super().__init__(data)
        self.imagename, devtag = windlass.tools.split_image(data['name'])
        if not self.version:
            self.version = devtag

        self.devtag = data.get('devtag', devtag)

    def __repr__(self):
        return (
            "windlass.image.Image(data=dict(name='%s', version='%s',"
            " devtag='%s'))" % (
                self.imagename, self.version, self.devtag
            )
        )

    def __str__(self):
        return '<Docker image %s (%s)>' % (self.name, self.version)

    def pull_image(self, remoteimage, imagename, tag):
        """Pull the remoteimage down

        And tag it with the imagename and tag.
        """
        client = docker.from_env(
            version='auto',
            timeout=180)
        logging.info("%s: Pulling image from %s", imagename, remoteimage)

        output = client.api.pull(remoteimage, stream=True)
        check_docker_stream(output)
        client.api.tag(remoteimage, imagename, tag)

        image = client.images.get('%s:%s' % (imagename, tag))
        return image

    def url(self, version=None, docker_image_registry=None, **kwargs):
        if version is None:
            version = self.version

        if docker_image_registry:
            return '%s/%s:%s' % (
                docker_image_registry.rstrip('/'), self.imagename, version)
        return '%s:%s' % (self.imagename, version)

    def build(self):
        # How to pass in no-docker-cache and docker-pull arguments.
        image_def = self.data

        if 'remote' in image_def:
            self.pull_image(
                image_def['remote'],
                *windlass.tools.split_image(image_def['name']))
        else:
            # TODO(kerrin) - repo should be relative the defining yaml file
            # and not the current working directory of the program. This change
            # is likely to break this.
            repopath = self.metadata['repopath']

            dockerfile = image_def.get('dockerfile', None)
            logging.debug('Expecting repository at %s' % repopath)
            build_image_from_local_repo(repopath,
                                        image_def['context'],
                                        image_def['name'],
                                        nocache=False,
                                        dockerfile=dockerfile,
                                        pull=True)
            logging.info('Get image %s completed', image_def['name'])

    def _delete_image(self, image):
        client = docker.from_env(
            version='auto',
            timeout=180)
        try:
            client.api.remove_image(image)
        except docker.errors.ImageNotFound:
            # Image isn't on system so no worries
            pass

    @windlass.api.fall_back('docker_image_registry')
    def delete(self, version=None, docker_image_registry=None, **kwargs):
        tag = version or self.version

        if docker_image_registry:
            self._delete_image(
                '%s/%s:%s' % (docker_image_registry, self.imagename, tag))
        self._delete_image('%s:%s' % (self.imagename, tag))

    @windlass.retry.simple()
    @windlass.api.fall_back('docker_image_registry')
    def download(self, version=None, docker_image_registry=None, **kwargs):
        client = docker.from_env(
            version='auto',
            timeout=180)
        if version is None and self.version is None:
            raise Exception('Must specify version of image to download.')

        if docker_image_registry is None:
            raise Exception(
                'docker_image_registry not set for image download. '
                'Where should we download from?')

        tag = version or self.version

        logging.info('Pinning image: %s to pin: %s' % (self.imagename, tag))
        remoteimage = '%s/%s:%s' % (docker_image_registry, self.imagename, tag)

        # Pull the remoteimage down and tag it with the name of artifact
        # and the requested version
        self.pull_image(remoteimage, self.imagename, tag)

        if tag != self.version:
            # Tag the image with the version but without the repository
            client.api.tag(remoteimage, self.imagename, self.version)

        # Apply devtag to this image also. Note that not all artifacts
        # support a devtag
        client.api.tag(remoteimage, self.imagename, self.devtag)

    def update_version(self, version):
        """Tag the image with a new version tag and update internal version.

        Does not attempt to remove the old version tag.
        """
        client = docker.from_env(
            version='auto',
            timeout=180)
        if version == self.version:
            logging.debug(
                "update_version(image): No version change (%s)", version
            )
            return
        client.api.tag(
            '%s:%s' % (self.imagename, self.version),
            self.imagename, tag=version,
        )
        return self.set_version(version)

    @windlass.retry.simple()
    @windlass.api.fall_back('docker_image_registry', first_only=True)
    def upload(self, version=None, docker_image_registry=None,
               docker_user=None, docker_password=None,
               **kwargs):
        client = docker.from_env(
            version='auto',
            timeout=180)
        # Start to phase out passing of version to upload.
        if version != self.version:
            logging.warning(
                "Changing image %s:%s version (to %s) during upload",
                self.imagename, self.version, version,
            )

        if 'remote' in kwargs:
            try:
                return kwargs['remote'].upload_docker(
                    self.imagename + ':' + self.version, upload_tag=version
                )
            except windlass.api.NoValidRemoteError:
                # Fall thru to old upload code.
                logging.debug(
                    "No docker endpoint configured for %s", kwargs['remote']
                )
        if docker_image_registry is None:
            raise Exception(
                'docker_image_registry not set for image upload. '
                'Unable to publish')

        if docker_user:
            auth_config = {
                'username': docker_user,
                'password': docker_password}
        else:
            auth_config = None

        # Local image name on the node
        local_fullname = self.url(self.version)

        # raises exception if imagename is missing
        try:
            client.images.get(local_fullname)
        except docker.errors.ImageNotFound as e:
            raise windlass.exc.MissingArtifact(
                'Image %s is missing.' % local_fullname,
                artifact_name=self.name,
                errors=[str(e)]
            )

        # Upload image with this tag
        upload_tag = version or self.version
        upload_name = '%s/%s' % (
            docker_image_registry.rstrip('/'), self.imagename)
        fullname = '%s:%s' % (upload_name, upload_tag)

        try:
            if docker_image_registry:
                client.api.tag(local_fullname, upload_name, upload_tag)
            push_image(upload_name, upload_tag, auth_config=auth_config)
        finally:
            if docker_image_registry:
                client.api.remove_image(fullname)

        logging.info('%s: Successfully pushed', self.name)

    def export_stream(self, version=None):
        client = docker.from_env(
            version='auto',
            timeout=180)
        img_name = self.imagename + ':' + self.version
        img = client.images.get(img_name)
        return img.save()

    def export(self, export_dir='.', export_name=None, version=None):
        client = docker.from_env(
            version='auto',
            timeout=180)
        img_name = self.imagename + ':' + self.version
        img = client.images.get(img_name)
        if export_name is None:
            ver = version or img.short_id[7:]
            export_name = "%s-%s.tar" % (self.name, ver)
        export_path = os.path.join(export_dir, export_name)
        logging.debug("Exporting image %s to %s", img_name, export_path)

        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        with open(export_path, 'wb') as f:
            for chunk in self.export_stream():
                f.write(chunk)
        return export_path

    def export_signable(self, export_dir='.', export_name=None, version=None):
        """Write the image ID (sha256 hash) to the export file"""
        client = docker.from_env(
            version='auto',
            timeout=180)
        img_name = self.imagename + ':' + self.version
        img = client.images.get(img_name)

        if export_name is None:
            # img.short_id starts 'sha256:...' - strip the prefix.
            ver = version or img.short_id[7:]
            export_name = "%s-%s.id" % (self.imagename, ver)
        export_path = os.path.join(export_dir, export_name)
        logging.debug("Exporting image ID for %s to %s", img_name, export_path)

        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        with open(export_path, 'w') as f:
            f.write(img.id)

        return export_path
