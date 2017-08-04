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

## Running windlass

Download or build all artifacts listed in a yaml file called example.yml:

    $ windlass --build-only example

Download all artifacts pinned to the latest validated versions. First check
out the product integration repository. And run the following:

    $ windlass --build-only
        --artifact-pins /path/to/integration_project/pins
        --artifactory-image-registry https://registry.artifactory.example.net
        example

Pushing container images to a proxy registry for use in a developer
environment. This allows developers to expose the container images stored
in docker to any virtual machines that may make up the developer environment.

    $ windlass --proxy-repository 127.0.0.1:5000 example

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

        - name: ubuntu
          location: helm
          values:
              image:
                  tag: "{version}"
                  repository: "{registry}/{name}"

will override the image.tag value to be the version been published and update
the chart to point to the correct image.
