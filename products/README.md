* Products that may be build as part of <dev-env>

Every product would have its own yml file which would be
product name. It would list all images and charts that
are required for it. This enables tooling to ensure
those images exist when <dev-env> is build.

This initial version supports building images from other
repos than <dev-env> only. For every product you need to
create yml file with name of product.yml to be stored in this
directory.

On top level is has to be dictionary and contain key 'images'
which would be list of dictionaries with following fields required:
 - name: string with name of image
 - repo: string with a link to git repo
 - context: directory in repo where docker context (Dockerfile and other files) are stored
Optionally:
 - branch: branch that you want to use

If particular repo is checked out then values of repo and branch would be
ignored and checked out copy would be used.

If image is build from remote repo or clean local repo it would be
tagged with ref_[last commit hex sha1] and if repo is dirty it
would be last_ref_[last commit hex sha1]. It will be also tagged
with branch_[branchname] which would be based on branch used
during build.
