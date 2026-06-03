# Flutter Workspace Automation

Workspace automation that supports embedded Flutter development.

A Python script, `flutter_workspace.py`, reads a configuration folder of JSON files (or a single JSON configuration file) and sets up a Flutter Workspace.

Discord Server: https://discord.gg/VKcpSHgjGQ

## Prerequisites

### Ubuntu

```bash
sudo apt install -y apt-utils python3
python3 -m pip install virtualenv
```

### Windows

1. Install [Visual Studio](https://visualstudio.microsoft.com/)
2. Install [CMake](https://cmake.org/download/)
3. Install python3 from the Windows Store and enable it for `cmd.exe`
4. Install the virtualenv module:

```bash
python3 -m pip install virtualenv
```

## Installation

```bash
git clone https://github.com/meta-flutter/workspace_automation.git
cd workspace_automation
./flutter_workspace.py
source ./setup_env.sh
```

## Usage

### Run Flutter App with desktop-auto

1. Login via GDM Wayland Session
2. Open a terminal
3. Source the environment and run your app:

```bash
source ${FLUTTER_WORKSPACE}/setup_env.sh
cd <path-to-your-app>
flutter run -d desktop-auto
```

### Run Flutter App with QEMU

1. Open a terminal and source the environment:

```bash
source ${FLUTTER_WORKSPACE}/setup_env.sh
```

2. Start QEMU and wait for the login prompt:

```bash
qemu_run
```

3. Add the remote host to your known hosts:

```bash
ssh -p 2222 root@localhost who
```

4. Navigate to your app and run it:

```bash
cd <path-to-your-app>
flutter run -run-qemu-master
```

### Create a hello_world Example

1. Login to Ubuntu desktop via Wayland Session
2. Open a terminal and run:

```bash
source ${FLUTTER_WORKSPACE}/setup_env.sh
cd ${FLUTTER_WORKSPACE}/app
flutter create hello_world -t app
cd hello_world
flutter run -d desktop-auto
```

### Running the `dart_pdf` Demo

```bash
./flutter_workspace.py --enable=pdfium
source ./setup_env.sh
export LD_LIBRARY_PATH=${FLUTTER_WORKSPACE}/app/pdfium/pdfium/out/Linux-Release/
pushd app/dart_pdf/demo
flutter run -d desktop-homescreen
```

## Command-Line Options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show help message and exit |
| `--clean` | Wipes workspace clean |
| `--config CONFIG` | Selects custom workspace configuration folder |
| `--flutter-version VERSION` | Select flutter version. Overrides config file key: `flutter_version` |
| `--github-token TOKEN` | Set github token. Overrides `_globals.json` key/value |
| `--cookie-file FILE` | Set cookie file to use. Overrides `_globals.json` key/value |
| `--fetch-engine` | Fetch engine artifacts |
| `--find-working-commit` | Find GIT commit where `flutter analyze` returns true |
| `--plex PLEX` | Platform Load Excludes (see below) |
| `--enable ENABLE` | Platform Load Enable Override (see below) |
| `--disable DISABLE` | Platform Load Disable Override (see below) |
| `--remote REMOTE` | Remote Platform Load Git Repo |
| `--enable-plugin PLUGIN` | Enable a plugin |
| `--disable-plugin PLUGIN` | Disable a plugin |
| `--fastboot PLATFORM` | Update the selected platform using fastboot |
| `--mask-rom PLATFORM` | Update the selected platform using Mask ROM |
| `--device-id ID` | Device id for flashing |
| `--stdin-file FILE` | Pass stdin for debugging |
| `--plugin-platform TYPE` | Specify plugin platform type |
| `--create-aot` | Generate AOT |
| `--app-path PATH` | Specify application path |
| `--copy-dconf-user` | Copy `$HOME/.config/dconf/user` to `$FLUTTER_WORKSPACE` |
| `--build-type BUILD_TYPE` | Specify build types (see below) |

### --plex / --disable

Excludes platform configurations by id. Separate multiple ids with `,`.

```bash
./flutter_workspace.py --plex=flatpak,firebase-cpp-sdk
```

This forces `FLUTTER_WORKSPACE_<platform-id>_LOAD=OFF`. This variable can be used reliably in a configuration type other than `dependency`.

### --enable

Enables platform configurations by id. Separate multiple ids with `,`.

```bash
./flutter_workspace.py --enable=flatpak
```

This forces `FLUTTER_WORKSPACE_<platform-id>_LOAD=ON`. This variable can be used reliably in a configuration type other than `dependency`.

### --build-type

Specify build types per platform. Format: `<platform_id>:<build_type>,<platform_id>:<build_type>`. Valid build types are `debug`, `profile`, `release`. If not specified, defaults to the globals `_BUILD_TYPE` value.

```bash
./flutter_workspace.py --build-type=my-platform:release,other-platform:profile
```

## create_aot.py

Creates `libapp.so` for use on a device. Requires an active `FLUTTER_WORKSPACE`.

```bash
source ./setup_env.sh
./create_aot --path <path-to-pubspec.yaml>
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `GEN_SNAPSHOT` | **(Required)** Path to the `gen_snapshot` executable |
| `PUB_CACHE` | Set via `source ./setup_env.sh` |
| `FLUTTER_WORKSPACE` | Set via `source ./setup_env.sh` |
| `FLUTTER_BUILD_ARGS` | Defaults to `bundle` |
| `LOCAL_ENGINE_HOST` | Defaults to `{flutter_sdk}/bin/cache/artifacts/engine/common` |
| `APP_GEN_SNAPSHOT_FLAGS` | Additional flags for gen_snapshot |
| `APP_GEN_SNAPSHOT_AOT_FILENAME` | Defaults to `libapp.so.{runtime_mode}` |
| `FLUTTER_PREBUILD_CMD` | Command to run before build |

## flutter_workspace.py

`flutter_workspace.py` automates the following:

* Establishes a workspace of known state
* Syncs repos into app folder
* Creates `.vscode` debug launcher file
* Sets up Flutter SDK and runtime=debug engine
* Loads platform types (QEMU, Docker, Remote, Host, Generic)
* Creates `setup_env.sh`

### Environment Variables

| Variable | Description |
|----------|-------------|
| `PREFER_LLVM` | (optional) Set the LLVM version to use. Defaults to `llvm-config` |
| `HARDWARE_THREADS` | (optional) Max hardware thread count for building/fetching. Useful for low RAM machines |

### Platform Configuration Variables

`FLUTTER_WORKSPACE_<config-id>_LOAD=[ON,OFF]`

Generated for each platform config. The initial value is determined by the platform config `load` key. It will be overridden to `OFF` via the `--plex=` option.

### Supported Platforms

| Platform | Architectures |
|----------|--------------|
| Ubuntu 20/22/24 | x86_64, aarch64 |
| Fedora 41/42/43/44 | x86_64 |
| macOS 13/14/15 | x86_64, arm64 (M1/M2) |
| Windows 10 | AMD64 |
| Windows 11 | AMD64, ARM64 (Surface Elite X) |

## Workspace Structure

A Flutter workspace contains:

```
<workspace>/
  flutter/                                        # Flutter SDK
  app/                                            # Development repositories
  app/ivi-homescreen/build/                       # flutter-auto binary
  .config/flutter_workspace/<platform-id>/        # Host runtime images
  .config/flutter_workspace/<platform>/           # QEMU image files
  .config/flutter_workspace/flutter-engine/       # Versioned libflutter_engine.so and icudtl.dat
  .config/flutter_workspace/<platform-id>/        # Custom-device configurations
  .config/flutter_workspace/pub_cache/            # Public cache
```

## JSON Configuration

`flutter_workspace_config.json` contains the following components:

* **globals** - `cookie_file`, `netrc`, `github_api`, `<any key>`
* **repos** - `git`
* **platform definition**

## Working with LLVM

### Set the Preferred Toolchain

To change the toolchain version, set the `PREFER_LLVM` variable:

```bash
PREFER_LLVM=10 ./flutter_workspace.py
```

If `PREFER_LLVM` is set, it overrides `clang-stable`.

If you have multiple instances of the same `llvm-config-<number>` file in `/usr`, the first occurring will be selected (this could be an Android NDK toolchain).

### List Available LLVM Installs

```bash
find /usr -type f -executable -name 'llvm-config*'
```

## Visual Studio Code

### Launching on Ubuntu

```bash
cd <your-flutter-workspace>
source ./setup_env.sh
code .
```

### Debugging with VS Code

`flutter_workspace.py` creates a `.vscode/launch.json` file if one is not present. It uses the repo json key `pubspec_path` — if present, an entry is added to `.vscode/launch.json`.
