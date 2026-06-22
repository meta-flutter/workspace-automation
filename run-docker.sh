#!/bin/bash

_NAME="run-docker.sh"
_DESCRIPTION="Run flutter_workspace.py in a docker container with the specified image and platform.
Use cases:
- Run workspace isolated from host environment
- Run workspace on a different platform from host (e.g. build linux/arm64 on linux/amd64)
- Run workspace on a different distro (e.g. test on both ubuntu and fedora)
- Run multiple workspaces concurrently
- Debug/simulate CI environment locally
"

_USAGE="Usage: $_NAME [docker_image] [-p platform] [--cmd=extra_command] [--args=workspace_args]
  docker_image: Docker image to use (default: ubuntu:22.04)
  -p platform: (optional) Target platform (default: amd64)
  --cmd=extra_command: (optional) Extra command to run after flutter_workspace.py
  --args=workspace_args: (optional) Extra arguments for flutter_workspace.py"

# first arg = docker image to use, e.g. ubuntu:22.04 or fedora:43
# default if not set: ubuntu:22.04
DEFAULT_IMAGE="ubuntu:22.04"

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  echo "$_NAME"
  echo "$_DESCRIPTION"
  echo "$_USAGE"
  exit 0
fi

if [ -z "$1" ]; then
  echo "No docker image specified, using default: $DEFAULT_IMAGE"
  IMAGE="$DEFAULT_IMAGE"
else
  IMAGE="$1"
  shift
fi

image_path=$(echo "$IMAGE" | tr '/' '-' | tr ':' '_')
mkdir -p ./.docker-cache/$image_path

# Remaining arguments (any order):
#   -p <platform>   : target platform (default: amd64)
#   --cmd=<command> : extra command to run after flutter_workspace.py
#   --args=<args>   : extra arguments for flutter_workspace.py
PLATFORM="amd64"
EXTRA_CMDS=""
WORKSPACE_ARGS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p)
      PLATFORM="$2"
      shift 2
      ;;
    -p*)
      PLATFORM="${1#-p}"
      shift
      ;;
    --cmd=*)
      EXTRA_CMDS="${1#--cmd=}"
      shift
      ;;
    --args=*)
      WORKSPACE_ARGS="${1#--args=}"
      shift
      ;;
    --help|-h)
      echo "$_NAME"
      echo "$_DESCRIPTION"
      echo "$_USAGE"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      shift
      ;;
  esac
done

# Print the configuration for debugging
echo "Using Docker image: $IMAGE"
echo "Target platform: $PLATFORM"
echo "Extra commands: $EXTRA_CMDS"
echo "Workspace arguments: $WORKSPACE_ARGS"

if [[ "$IMAGE" == *ubuntu:* ]]; then
  docker run \
    --platform linux/$PLATFORM \
    --rm -it \
    -e HOST_UID=$(id -u) \
    -e HOST_GID=$(id -g) \
    -e DEBIAN_FRONTEND=noninteractive \
    -e NONINTERACTIVE=true \
    -e TZ=$TZ \
    -e LANGUAGE=en_US.UTF-8 \
    -e LANG=en_US.UTF-8 \
    -e LC_ALL=en_US.UTF-8 \
    -e CI=true \
    -e EXTRA_CMDS="${EXTRA_CMDS}" \
    -e WORKSPACE_ARGS="${WORKSPACE_ARGS}" \
    -e PREFER_LLVM=${PREFER_LLVM} \
    -v ./.docker-cache/$image_path:/data/workspace-automation/.cache \
    -v .:/tmp/workspace-automation:ro \
    $IMAGE \
    bash -O extglob -O dotglob -c 'set -x; (mkdir -p /data/workspace-automation || true) && cp -r /tmp/workspace-automation/!(*cache) /data/workspace-automation/ && cd /data/workspace-automation && apt update -yq && apt-get -o "Dir::Cache::archives=/data/workspace-automation/.cache/apt" install -yq sudo git python3 apt-utils locales && locale-gen en_US.UTF-8 && dpkg-reconfigure locales && git clean -xffdxx --exclude=".cache" && existing_user=$(getent passwd $HOST_UID | cut -d: -f1); [ -n "$existing_user" ] && userdel -r "$existing_user" 2>/dev/null || true && existing_group=$(getent group $HOST_GID | cut -d: -f1); [ -n "$existing_group" ] && groupdel "$existing_group" 2>/dev/null || true && groupadd -g $HOST_GID user && useradd -m -u $HOST_UID -g $HOST_GID -s /bin/bash user && echo "user ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers && echo "debconf debconf/frontend select Noninteractive" | debconf-set-selections && chown -R user:user /data/workspace-automation && su user -p -c "HOME=/home/user; export HOME; env; cd /data/workspace-automation && ./flutter_workspace.py ${WORKSPACE_ARGS} && ${EXTRA_CMDS:-true}"'
elif [[ "$IMAGE" == *fedora:* ]]; then
  docker run \
    --platform linux/$PLATFORM \
    --rm -it \
    -e HOST_UID=$(id -u) \
    -e HOST_GID=$(id -g) \
    -e NONINTERACTIVE=true \
    -e TZ=$TZ \
    -e LANGUAGE=en_US.UTF-8 \
    -e LANG=en_US.UTF-8 \
    -e LC_ALL=en_US.UTF-8 \
    -e CI=true \
    -e EXTRA_CMDS="${EXTRA_CMDS}" \
    -e WORKSPACE_ARGS="${WORKSPACE_ARGS}" \
    -e PREFER_LLVM=${PREFER_LLVM} \
    -v ./.docker-cache/$image_path:/data/workspace-automation/.cache:z \
    -v .:/tmp/workspace-automation:ro,z \
    $IMAGE \
    bash -O extglob -O dotglob -c 'set -x; (mkdir -p /data/workspace-automation || true) && cp -r /tmp/workspace-automation/!(*cache) /data/workspace-automation/ && cd /data/workspace-automation && dnf --setopt="cachedir=/data/workspace-automation/.cache/dnf" install -y sudo git which python3 glibc-langpack-en && python3 -m pip install --upgrade pip && localedef -i en_US -f UTF-8 en_US.UTF-8 && git clean -xffdxx --exclude=".cache" && existing_user=$(getent passwd $HOST_UID | cut -d: -f1); [ -n "$existing_user" ] && userdel -r "$existing_user" 2>/dev/null || true && existing_group=$(getent group $HOST_GID | cut -d: -f1); [ -n "$existing_group" ] && groupdel "$existing_group" 2>/dev/null || true && groupadd -g $HOST_GID user && useradd -m -u $HOST_UID -g $HOST_GID -s /bin/bash user && echo "user ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers && chown -R user:user /data/workspace-automation && su user -c "HOME=/home/user; export HOME; export CI=${CI}; export PREFER_LLVM=${PREFER_LLVM}; unset PYTHONHOME PYTHONPATH LD_LIBRARY_PATH OPENSSL_CONF OPENSSL_MODULES SSL_CERT_FILE SSL_CERT_DIR; env; cd /data/workspace-automation && ./flutter_workspace.py ${WORKSPACE_ARGS} && ${EXTRA_CMDS:-true}"'
else
  echo "Unsupported docker image. Please use an ubuntu:* or fedora:* image."
fi