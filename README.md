# Flutter Workspace Automation

Workspace Automation that supports embedded Flutter development

We developed a Python script, `flutter_workspace.py` to automate embedded flutter setup.
This script reads a configuration folder of JSON files, or a single JSON configuration file and sets up a Flutter Workspace.


### setup_flutter_workspace.py

flutter_workspace.py does the following tasks automatically for you

* Establishes a work space of a known state
* Installs Flutter SDK
* Downloads Flutter runtime=debug engine
* Clones specified repositories into app folder to selected revision
* Creates setup_env.sh
* Installs defined platforms, which can include:
    * Binary artifacts - http, docker, qemu, etc
    * Installs custom-device per platform
* Creates .vscode debug launcher file when pubspec_path is specified  
* Runs on Linux and Mac


### Flutter Workspace

A Flutter workspace contains the following components

* Flutter SDK
* Development Repositories
* Host Runtime images
* flutter-auto binary
* QEMU image
* Versioned x86_64 libflutter_engine.so and icudtl.dat (debug)
* Custom-device configurations
* Public Cache


### JSON Configuration 

flutter_workspace_config.json contains the following components

* General: flutter-version, github_token, and Platforms Object
* General: id, type, arch, flutter_runtime
* Runtime: key/values related to installing binary runtime
* Custom-device: key/values directly installed as custom-device
* Repos Object: Array of GIT repos to clone: uri, branch, rev
* Minimal configuration: {"flutter-version":"stable","platforms":[],"repos":[]}


### Installation

```
git clone https://github.com/meta-flutter/workspace_automation.git
./flutter_workspace.py
```


### Run flutter app with desktop-auto 

* Login via GDM Wayland Session
* Open Terminal and type
* `source ${FLUTTER_WORKSPACE}/setup_env.sh`
* Navigate to your favorite app
* `flutter run -d desktop-auto`


### Run flutter app with QEMU 

* Open Terminal and type
* `source ${FLUTTER_WORKSPACE}/setup_env.sh`
* Type `qemu_run`
* Wait until QEMU image reaches login prompt
* Run `ssh –p 2222 root@localhost who` to add remote host to ~/.ssh/known_hosts
* Navigate to your favorite app
* `flutter run -d AGL-qemu`


### Create hello_world flutter example 

* Login to Ubuntu desktop via Wayland Session
* Open Terminal and type
* `source ${FLUTTER_WORKSPACE}/setup_env.sh`
* `cd ${FLUTTER_WORKSPACE}/app`
* `flutter create hello_world -t app`
* `cd hello_world`
* `flutter run -d desktop-auto`

### Visual Studio Code

#### Launching on Ubuntu

```
    cd <your flutter workspace>
    source ./setup_env.sh
    code .
```

#### Debugging with VS Code

`flutter_workspace.py` creates a `.vscode/launch.json` file if one is not present.
It uses the repo configuration key `pubspec_path`.  If this key is present in the repo
entry, then it will add entry to `.vscode/launch.json`.

