* Products that may be build as part of <dev-env>

Every product would have its own yml file which would be
product name. It would list all images and charts that
are required for it. This enables tooling to ensure
those images exist when <dev-env> is build.

On top level is has to be dictionary and contain key 'images'
which would be list of dictionaries with following fields required for images:
 - name: string with name of image, image would be in <remote> docker repository as <remote>/name
 - repo: string with a link to git repo or dot if <dev-env> repo is used, required only for built images
 - context: directory in repo where docker context (Dockerfile and other files) are stored, required only for built images
 - remote: Remote docker repository path, required only for pulled images
Optionally:
 - branch: branch that you want to use, default is master, applicable only to built images
 - description: Image description, it is currently used for help section of cloud config
 - template_variable: Name of variable for jinja2 contexts used by cloud config

If particular repo is checked out then values of repo and branch would be
ignored and checked out copy would be used.

If image is build from remote repo or clean local repo it would be
tagged with ref_[last commit hex sha1] and if repo is dirty it
would be last_ref_[last commit hex sha1]. It will be also tagged
with branch_[branchname] which would be based on branch used
during build.

If image has tag `nowindlass` it will be ignored by windlass tool.
