# Flutter Workspace Automation

Workspace Automation that supports embedded Flutter development

We developed a Python script, `flutter_workspace.py` to automate embedded flutter setup.
This script reads a configuration folder of JSON files, or a single JSON configuration file and sets up a Flutter Workspace.


### flutter_workspace.py

flutter_workspace.py does the following tasks automatically for you

* Establishes a workspace of known state
* Sync repos into app folder
* .vscode debug launcher file
* Flutter SDK
* Flutter runtime=debug engine
* Loads platform types
  * QEMU, Docker, Remote, Host, Generic
  * Each type uses a specific configuration
* Create setup_env.sh
* 
* Tested on Linux and Mac
  * Ubuntu 20 (x86_64)
  * Ubuntu 22 (x86_64)
  * Fedora 37 (x86_64)
  * Mac M1/M2 (arm64)


### Flutter Workspace

A Flutter workspace contains

* Flutter SDK
  * flutter
* Development Repositories (app)
  * app
* Host Runtime images
  * .config/flutter_workspace/<platform-id>
* flutter-auto binary
  * app/ivi-homescreen/build
* QEMU image
  * .config/flutter_workspace/<platform>/<qemu files>)
* Versioned x86_64 libflutter_engine.so and icudtl.dat
  * ./config/flutter_workspace/flutter-engine
* Custom-device configurations
  * ./config/flutter_workspace/<platform-id>
* Public Cache
  * .config/flutter_workspace/pub_cache


### JSON Configuration 

flutter_workspace_config.json contains the following components

* globals
  * cookie_file
  * netrc
  * github_api
  * <any key>
* repos
  * git
* platform definition


### Installation

```
git clone https://github.com/meta-flutter/workspace_automation.git
./flutter_workspace.py
```

### Options

#### --clean

Wipes workspace before creating

#### --config=<file or folder>

Pass configuration JSON file, or folder path.


#### --flutter-version=x.x.x

Override config/_globals.json key "flutter_version"

#### --fetch-engine

Fetch libflutter_engine.so and update bundle cache

#### --version-files=<folder>

Pass folder for storing dart and engine json files.

#### --plex="..."

Platform Load Exceptions.  Pass platform-id values.  Space is delimiter

#### --stdin-file

Use for debugging


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
* `flutter run -run-qemu-master`


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
It uses the repo json key `pubspec_path`.  If this key is present in the repo
json, then it will add entry to `.vscode/launch.json`.


#### Impeller 3D

## Build engine, embedder, and App

    git clone https://github.com/meta-flutter/workspace-automation -b jw/impeller 

edit `configs/_globals.json` and add your github dev token to github_token value

start virtual python environment if desired

    ./flutter_workspace.py
    . ./setup_env.sh
    cd app/gallery
    flutter run --enable-impeller --local-engine=host_debug_unopt --local-engine-host=host_debug_unopt --local-engine-src-path=/mnt/raid10/workspace-automation/.config/flutter_workspace/flutter-engine/engine/src -d desktop-homescreen

## CLion

Open root of ivi-homescreen project

* Edit homescreen target
    * Set Program Arguments
    
    --b=/mnt/raid10/workspace-automation/app/gallery/.desktop-homescreen --w=1920 --h=720 --enable-impeller --verbose-logging --p=1

    * Update Enivronment Settings to include
    
    SPDLOG_LEVEL=trace;MESA_DEBUG=1;EGL_LOG_LEVEL=info

2. Click Debug


To change pixel_ratio, change CLI argument `--p`.  e.g. `--p=0.5`
