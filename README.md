(c) Copyright 2017 Hewlett Packard Enterprise Development LP

Licensed under the Apache License, Version 2.0 (the "License"); you may
not use this file except in compliance with the License. You may obtain
a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

[TOC]

# Windlass

Windlass is a tool to fetch and manage artifacts required for running a
development environment, running some development task, or collecting
artifacts for some task like building a customer kit.

Windlass is also integrated with Zing CI. So we can use windlass to push artifacts
built by Zing to Artifactory, generate a database of the artifacts version
pins. Developers, CI and build jobs can use this database to pull down the
exact set of artifacts used in a product build, the artifacts in use during
a CI job ...

We pass Windlass one or more yaml files that will tell it the artifacts it
needs, the type of artifact. From this Windlass will deduce how to download
or build these artifacts.

Windlass is designed so that we can meet the following workflows.

1. Download all artifacts that have been validated by a product integration
   test.

1. Used by the product integration test to collect all proposed artifacts
   to test has part of an integration test with the rest of the product.

1. Used by developers to download all validated artifacts, so that they can
   test the same kit has run by customers or to test the exact same kit
   been proposed in CI but which may be failing.

1. Used by developers to download, build and test their code locally.
   Developers will download the artifacts and build only the artifacts that
   they are working on fixing or improving. They will then be able to deploy
   these artifacts to their local development environment.

## Installing windlass

Following requirements must be met:

1.   python3 or newer installed on your machine

2.   https_proxy set up if your machine is behind proxy

Install windlass with following steps:

1.   Create the python3 virtualenv `virtualenv -p python3 windlassvenv`

2.   Load the virtualenv `source ./windlassvenv/bin/activate`

3.   Install windlass from sources `pip install -e .`

## Running windlass

### Building

To build all artifacts listed in a yaml file called example.yaml:

    $ windlass --build-only example.yaml

### Download

Download all artifacts listed in example.yaml with the version
_0.0.0-abe8b542c9f7b207b05fb09a379f43dfec983d79_:

    $ windlass --download --download-version 0.0.0-abe8b542c9f7b207b05fb09a379f43dfec983d79
        --download-docker-registry https://registry.example.net
        example.yaml

### Uploading

Pushing container images to a proxy registry for use in a developer
environment. This allows developers to expose the container images stored
in docker to any virtual machines that may make up the developer environment.

    $ windlass --push-only --push-docker-registry 127.0.0.1:5000 example.yaml

### Building and uploading

If you want to build all images in example.yaml and push them to a local docker
registry listening on 127.0.0.1:5000 then we do this in one step instead of
building and then pushing:

    $ windlass --push-docker-registry 127.0.0.1:5000 example.yaml

## Artifact types

### Images

When dealing with docker container images Windlass has 3 uses to cover:

1. Download image from third party team:

        images:
          - name: <org>/zuul

   How this image is built isn't of concern to use. We will download this from
   the specific docker registry defaulting to
   _registry.hub.docker.com_ and then tag this image with
   name specified here. If we run _docker images_ after this we will see the
   following images:

        <org>/zuul   latest                                     2e34ff20ec5c   5 days ago   150MB
        <org>/zuul   82f9b2ce302a6953065a1b347e1ba98874b7b7eb   2e34ff20ec5c   5 days ago   150MB

1. Remote repositories:

        images:
          - name: <org>/rabbitmq:3.5.7-management
            remote: rabbitmq:3.5.7-management

   This will download the image _rabbitmq:3.5.7-management_ and tag it as
   _<org>/rabbitmq:3.5.7-management_

        rabbitmq       3.5.7-management   6a09913714a8   18 months ago   304MB
        <org>/rabbitmq 3.5.7-management   6a09913714a8   18 months ago   304MB

1. Build an image from a git repository, local or remote:

        images:
          - name: <org>/zuul
            repo: https://github.com/<org>/zuul.git
            context: zuul
          - name: zing/windlass
            repo: .

   This will checkout the _repo_ (unless it is the current working repository)
   and run _docker build_ in the context supplied. In the case of <org>/zuul
   we checkout https://github.com/<org>/zuul.git repository. And run the equivalent of:

        $ docker build -t <org>/zuul --build-arg .... ./zuul/

   You will see the following images:

        <org>/zuul   branch_master   2e34ff20ec5c   5 days ago   150MB
        <org>/zuul   latest          2e34ff20ec5c   5 days ago   150MB
        <org>/zuul   ref_82f9bd...   2e34ff20ec5c   5 days ago   150MB

### Charts

"Helm uses a packaging format called charts. A chart is a collection of files
that describe a related set of Kubernetes resources."

We have a requirement to publish images and charts under different unique
versions from CI. When we do so we can break the charts as the reference
to the image they deploy will change from a development tag to an unique
tag. In order to keep the charts working after publication we have added a
mechanism update the references by modifying the charts values.yaml file.
This mechanism is only applied when we upload a chart with under a specific
version.

In the yaml configuration files, we can specify a set of values we wish to
override in the values.yaml. We can currently reference the _version+_,
_name_ and _registry_ we are upload to.

For example:

        charts:

          - name: ubuntu
            location: helm
            values:
              image:
                tag: "{version}"
                repository: "{registry}/{name}"

will override the image.tag value to be the version been published and update
the chart to point to the correct image.

## Product integration

Windlass can manage lots of artifacts based on a set of pins. Windlass can parse
a configuration file called _product-integration.yaml_ file, that it will use
to generate a list of Artifact objects that it can now manage. Generally this is
performed via Python api call: _windlass.pins.read\_pins_ and
_windlass.pins.write\_pins_.

The format of the product integration test is dictionary of sections:

    #
    # pins: is a dictionary sections used to control how we pin
    # artifacts.
    #
    pins:
      section1:
          # type: type tells us how this section will manage the pins.
          #
          # Current choice of:
          # - ImagePins
          # - LandscaperPins
          #
          # The choice of here can change default values of variables.
          #
          type: ImagesPin

          #
          # pins_dir: Context directory containing all the managed pins.
          #
          # Default: 'pins'
          #
          # Applies: all types.
          #
          pins_dir: 'pins'

          #
          # pins_files_globs: Location of pins
          #
          # Uses python 3 glob https://docs.python.org/3/library/glob.html
          # module to iterate over all the configuration files.
          #
          # Applies: all types.
          #
          # Default: ['{pins_dir}/**/*.yaml']
          #

          #
          # ignore: [] Ignore artifacts in set
          #
          # List of artifacts which we ignore for this section. That
          # is we don't write out the pins for these artifacts.
          #

          #
          # only: [] Only artifacts in set
          #
          # The only list of artifacts we write pins out for in this
          # section. If a artifact is not in this section then it is
          # not written out.
          #


## Python API

### windlass.api.Windlass(list_of_product_files)

### windlass.pins.Pins

#### windlass.pins.ImagePins

#### windlass.pins.LanderscaperPins
