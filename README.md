# Flutter Workspace Automation

Workspace Automation that supports embedded Flutter development

We developed a Python script, `flutter_workspace.py` to automate embedded flutter setup.
This script reads a configuration folder of JSON files, or a single JSON configuration file and sets up a Flutter Workspace.

### Discord Server https://discord.gg/VKcpSHgjGQ

### create_aot.py

create AOT is used to create libapp.so for use on a device.

Example use:

    ./create_aot --path <path that holds a pubspec.yaml>

Expects to be run from an active FLUTTER_WORKSPACE.  Meaning you need to source you environment first.

### create_recipes.py

creates a Yocto recipe for every pubspec.yaml found in a path folder.  It will recursively iterate all subfolders.

Example use:
    
    ./create_recipes.py --path app/packages/ --license LICENSE --license_type BSD3-Clause --author "Google" --out ./tmp


#### Environmental variables used by script:

* GEN_SNAPSHOT - (Required) Set GEN_SNAPSHOT to location of executable gen_snapshot

* PUB_CACHE - Set using `source ./setup_env.sh`

* FLUTTER_WORKSPACE - Set using `source ./setup_env.sh`

* FLUTTER_BUILD_ARGS - Defaults to 'bundle'

* LOCAL_ENGINE_HOST - Defaults to f'{flutter_sdk}/bin/cache/artifacts/engine/common'

* APP_GEN_SNAPSHOT_FLAGS

* APP_GEN_SNAPSHOT_AOT_FILENAME - Defaults to 'libapp.so.{runtime_mode}'

* FLUTTER_PREBUILD_CMD

### roll_meta_flutter.py

Updates all Flutter App recipes in meta-flutter using json as data source.  The default data source is configs/flutter-apps.json

Example use

    ./roll_meta_flutter.py --path `pwd`/tmp

Default pubspec.yaml filter tokens

    _android/pubspec.yaml
    _ios/pubspec.yaml
    _linux/pubspec.yaml
    _macos/pubspec.yaml
    _platform_interface/pubspec.yaml
    _web/pubspec.yaml
    _windows/pubspec.yaml

Default recipe filename filter tokens

    -apple_
    -avfoundation_
    -darwin_
    -linux_
    -web_

_Note: Exclude filters are added to json as "exclude" string array.  The value to populate exclude filter is the `FLUTTER_APPLICATION_PATH` value.  An empty string is valid._

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

#### --config=<folder>

Pass configuration folder path.


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

