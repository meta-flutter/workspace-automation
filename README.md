# Flutter Workspace Automation

Workspace Automation that supports embedded Flutter development

We developed a Python script, `flutter_workspace.py` to automate embedded flutter setup.
This script reads a configuration folder of JSON files, or a single JSON configuration file and sets up a Flutter Workspace.

#### Discord Server https://discord.gg/VKcpSHgjGQ

### Minimum requirements

* Ubuntu

    sudo apt install -y apt-utils python3

* Windows

- Install Visual Studio
- Install CMake
- Install python3 from the Windows Store - enable for cmd.exe

-Install the python virtualenv module

    python3 -m pip install virtualenv

-Requirements to build `filament-windows/flutter-engine-windows`
  
  -Enable long path support for git

      git config --global core.longpaths true

  -Enable Developer Mode to allow symlink creation without Admin rights

    On Windows 10/11, enabling Developer Mode allows non-admin users to create symlinks

    Go to Settings > Search for developer settings
    Turn on Developer Mode
    Restart your terminal

  -Install Windows 10 SDK from Visual Studio installer

   if ARM64 Windows machine copy `C:\Program Files (x86)\Windows Kits\10\Debuggers\arm64` to `C:\Program Files (x86)\Windows Kits\10\Debuggers\arm64` to appease flutter/tools/gen.bat

  -Install ninja and add to path after depot_tools

  -Optional install WinDgb - AKA Wind-Bag
  
    winget install Microsoft.WinDbg

  -Running

    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
    .\flutter_workspace.ps1 --enable "filament-windows,flutter-engine-windows"

  -Running setup_env.ps1

    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
    .\setup_env.ps1

### create_aot.py

create AOT is used to create libapp.so for use on a device.  It requires an active FLUTTER_WORKSPACE.

Example use:

    source ./setup_env.sh
    ./create_aot --path <path that holds a pubspec.yaml>

#### Environmental variables used by script

* GEN_SNAPSHOT - (Required) Set GEN_SNAPSHOT to location of executable gen_snapshot

* PUB_CACHE - Set using `source ./setup_env.sh`

* FLUTTER_WORKSPACE - Set using `source ./setup_env.sh`

* FLUTTER_BUILD_ARGS - Defaults to 'bundle'

* LOCAL_ENGINE_HOST - Defaults to f'{flutter_sdk}/bin/cache/artifacts/engine/common'

* APP_GEN_SNAPSHOT_FLAGS

* APP_GEN_SNAPSHOT_AOT_FILENAME - Defaults to 'libapp.so.{runtime_mode}'

* FLUTTER_PREBUILD_CMD

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
* Tested on Linux, Mac, and Windows
  * Ubuntu 20/22/24 (x86_64, aarch64)
  * Fedora 40/41/42 (x86_64)
  * macOS 13/14/15 (x86_64, arm64) - Mac M1/M2
  * Windows 10 (AMD64)
  * Windows 11 (AMD64, ARM64) - Windows Surface Elite X

#### Environmental Variables

* PREFER_LLVM - (optional) set the LLVM version to use.  If not found, defaults to using `llvm-config`.

* HARDWARE_THREADS - (optional) set the maximum hardware thread count used in building and fetching.  Used for low RAM machines.

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


### Platform configuration environmental variables

* `FLUTTER_WORKSPACE_<config id>)_LOAD=[ON,OFF]`
  This environmental variable is generated for each platform config.  The initial value is determined by the platform config `load` key value.  It will be overriden to `OFF` via the `--plex=` command line option.


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

Platform Load Exceptions.  Pass platform-id values.  Select multiple platform ids by seperating with `,`.

e.g. `--plex=filament,firebase-cpp-sdk`

This option also has the impact of forcing the environmental variable `FLUTTER_WORKSPACE_<platfor id>)_LOAD=OFF`.  This variable can be used reliably in a configuration type other than `dependency`.

#### --enable="..."

Enable Platform Configuration(s).  Pass platform-id values.  Select multiple platform ids by seperating with `,`.

e.g. `--enable=filament`

This option also has the impact of forcing the environmental variable `FLUTTER_WORKSPACE_<platfor id>)_LOAD=ON`.  This variable can be used reliably in a configuration type other than `dependency`.

#### --disable="..."

Alias to --plex.  See `--plex` description


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


### Running `dart_pdf` demo

    ./flutter_workspace.py --enable=pdfium
    source ./setup_env.sh
    export LD_LIBRARY_PATH=${FLUTTER_WORKSPACE}/app/pdfium/pdfium/out/Linux-Release/
    pushd app/dart_pdf/demo
    flutter run -d desktop-homescreen


### Working with LLVM

#### Set the preferred LLVM toolchain

To change the toolchain version used by flutter_workspace use the `PREFER_LLVM` variable
```
PREFER_LLVM=10 ./flutter_workspace.py
```

If the `PREFER_LLVM` key is set it overrides `clang-stable`.

If you have multiple instances of the same llvm-config-<number> file present in `/usr`, the first ocurring will be selected.  This could be an Android NDK toolchain.

Refer to listing available LLVM installs for debugging toolchain selection problems.

#### List available LLVM installs
```
find /usr -type f -executable -name 'llvm-config*'
```

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
