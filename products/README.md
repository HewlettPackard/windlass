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
 - dockerfile: path to docker file inside context, as one would pass in '-f' option in docker build

If particular repo is checked out then values of repo and branch would be
ignored and checked out copy would be used.

If image is build from remote repo or clean local repo it would be
tagged with ref_[last commit hex sha1] and if repo is dirty it
would be last_ref_[last commit hex sha1]. It will be also tagged
with branch_[branchname] which would be based on branch used
during build.

If image has tag `nowindlass` it will be ignored by windlass tool.

For charts there has to have key 'charts' on top level dictionary, which would
contain list of dictionatires with following fields:
 - name: chart name
If chart is coming from GIT repository there must be following fields:
 - repo: linkt to repo or dot if <dev-env> repo is used
 - location: directory in repo containing chart directory
 - branch: optionally a branch to be used, default value is 'master'

If repository is checked out at same level as <dev-env> then a working
copy would be used and branch value will be ignored.

If chart is coming from Helm repository there must be following fields:
 - remote: URL to helm repository
 - version: chart version

 Example includes same charts in both ways:
         charts:

           - name: ceph-rgw
             version: 0.1.0
             remote: "https://pages.github.com/<org>/helm-repo/"

           - name: ceph-rgw
             branch: master
             location: "."
             repo: "https://github.com/<org>/helm-repo.git"
