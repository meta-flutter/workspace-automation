# Flutter Workspace Automation

Workspace Automation that supports embedded Flutter development

We developed a Python script, `flutter_workspace.py` to automate embedded flutter setup.
This script reads a configuration folder of JSON files, or a single JSON configuration file and sets up a Flutter Workspace.

**Discord Server https://discord.gg/VKcpSHgjGQ**

## System Setup

### Ubuntu

Install required packages:

```sh
sudo apt install -y apt-utils python3
```

### Windows

1. **Install Visual Studio**  
  - Include Desktop development with C++ workload.

2. **Install CMake**  
  - Download from [cmake.org](https://cmake.org/download/).

3. **Install Python 3**  
  - Use the Windows Store or download from [python.org](https://www.python.org/downloads/windows/).
  - Enable Python for `cmd.exe` during installation.

4. **Install the Python virtualenv module**:

   ```sh
   python3 -m pip install virtualenv
   ```

5. **Requirements to build `filament-windows/flutter-engine-windows`:**

   - **Enable long path support for git:**

      ```sh
      git config --global core.longpaths true
      ```

   - **Enable Developer Mode to allow symlink creation without Admin rights:**
      - Go to *Settings* > search for *Developer settings*.
      - Turn on *Developer Mode*.
      - Restart your terminal.

   - **Install Windows 10 SDK**  
    - Use the Visual Studio Installer to add the Windows 10 SDK.

   - **For ARM64 Windows machines:**  
    - Copy `C:\Program Files (x86)\Windows Kits\10\Debuggers\arm64` to `C:\Program Files (x86)\Windows Kits\10\Debuggers\arm64` to appease `flutter/tools/gen.bat`.

   - **Install ninja and add to PATH after depot_tools.**

   - **Optional: Install WinDbg:**

      ```sh
      winget install Microsoft.WinDbg
      ```

6. **Running scripts:**

   - **PowerShell:**  
    Set execution policy and run workspace automation:

      ```powershell
      Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
      .\flutter_workspace.ps1 --enable "filament-windows,flutter-engine-windows"
      ```

   - **Setup environment:**

      ```powershell
      Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
      .\setup_env.ps1
      ```

## `create_aot.py`

The `create_aot.py` script generates a `libapp.so` file for deployment on a device. It requires an active `FLUTTER_WORKSPACE` environment.

**Example usage:**

```sh
source ./setup_env.sh
./create_aot --path <path-containing-pubspec.yaml>
```

**Environment variables used:**

- `GEN_SNAPSHOT` (required): Path to the `gen_snapshot` executable.
- `PUB_CACHE`: Set by sourcing `./setup_env.sh`.
- `FLUTTER_WORKSPACE`: Set by sourcing `./setup_env.sh`.
- `FLUTTER_BUILD_ARGS`: Defaults to `bundle`.
- `LOCAL_ENGINE_HOST`: Defaults to `${flutter_sdk}/bin/cache/artifacts/engine/common`.
- `APP_GEN_SNAPSHOT_FLAGS`: Additional flags for `gen_snapshot`.
- `APP_GEN_SNAPSHOT_AOT_FILENAME`: Defaults to `libapp.so.{runtime_mode}`.
- `FLUTTER_PREBUILD_CMD`: Optional pre-build command.

---

## `flutter_workspace.py`

The `flutter_workspace.py` script automates the setup and management of a Flutter workspace for embedded development.

**Key features:**

- Initializes a workspace in a known state.
- Syncs repositories into the `app` folder.
- Generates a `.vscode` debug launcher file.
- Manages the Flutter SDK and runtime engine.
- Loads platform types (QEMU, Docker, Remote, Host, Generic) with specific configurations.
- Creates `setup_env.sh` for environment setup.
- Tested on Linux, macOS, and Windows (see supported versions below).

**Supported platforms:**

- Ubuntu 20/22/24 (x86_64, aarch64)
- Fedora 40/41/42 (x86_64)
- macOS 13/14/15 (x86_64, arm64) - Mac M1/M2
- Windows 10 (AMD64)
- Windows 11 (AMD64, ARM64) - Windows Surface Elite X

**Environment variables:**

- `PREFER_LLVM` (optional): Specify the LLVM version to use. Defaults to `llvm-config` if not set.
- `HARDWARE_THREADS` (optional): Limit hardware thread usage for building/fetching (useful for low RAM systems).

---

## Flutter Workspace Structure

A Flutter workspace typically contains:

- **Flutter SDK** (`flutter`)
- **Development repositories** (`app`)
- **Host runtime images** (`.config/flutter_workspace/<platform-id>`)
- **flutter-auto binary** (`app/ivi-homescreen/build`)
- **QEMU images** (`.config/flutter_workspace/<platform>/<qemu files>`)
- **Versioned engine files** (`./config/flutter_workspace/flutter-engine`)
- **Custom device configurations** (`./config/flutter_workspace/<platform-id>`)
- **Pub cache** (`.config/flutter_workspace/pub_cache`)

---

## JSON Configuration

The `flutter_workspace_config.json` file includes:

- **globals**: General settings (e.g., `cookie_file`, `netrc`, `github_api`)
- **repos**: Repository definitions (e.g., `git`)
- **platform**: Platform-specific configuration

---

## Platform Configuration Environment Variables

For each platform config, an environment variable is generated:

```
FLUTTER_WORKSPACE_<config_id>_LOAD=[ON|OFF]
```

- The initial value is set by the platform config's `load` key.
- Can be overridden with the `--plex=` command-line option.

Example:

```sh
./flutter_workspace.py --enable=filament --disable=rive-text
```

---

## Installation

```sh
git clone https://github.com/meta-flutter/workspace_automation.git
./flutter_workspace.py
```

---

## Command-Line Options

- `--clean`: Wipe workspace before creating.
- `--config=<folder>`: Specify configuration folder path.
- `--flutter-version=x.x.x`: Override Flutter version in config.
- `--fetch-engine`: Fetch `libflutter_engine.so` and update bundle cache.
- `--version-files=<folder>`: Specify folder for Dart and engine JSON files.
- `--plex="..."`: Platform Load Exceptions. Comma-separated platform IDs (e.g., `--plex=filament,firebase-cpp-sdk`). Forces `FLUTTER_WORKSPACE_<platform_id>_LOAD=OFF`.
- `--enable="..."`: Enable platform configurations. Comma-separated platform IDs (e.g., `--enable=filament`). Forces `FLUTTER_WORKSPACE_<platform_id>_LOAD=ON`.
- `--disable="..."`: Alias for `--plex`.
- `--stdin-file`: Use for debugging.

---

## Running Flutter Apps

### On Desktop

1. Log in via GDM Wayland Session.
2. Open a terminal:
  ```sh
  source ${FLUTTER_WORKSPACE}/setup_env.sh
  ```
3. Navigate to your app directory.
4. Run:
  ```sh
  flutter run -d desktop-auto
  ```

### With QEMU

1. Open a terminal:
  ```sh
  source ${FLUTTER_WORKSPACE}/setup_env.sh
  qemu_run
  ```
2. Wait for the QEMU image to reach the login prompt.
3. Add the remote host to `~/.ssh/known_hosts`:
  ```sh
  ssh -p 2222 root@localhost who
  ```
4. Navigate to your app directory and run:
  ```sh
  flutter run -run-qemu-master
  ```

---

## Creating a Hello World Flutter Example

1. Log in to Ubuntu desktop via Wayland Session.
2. Open a terminal:
  ```sh
  source ${FLUTTER_WORKSPACE}/setup_env.sh
  cd ${FLUTTER_WORKSPACE}/app
  flutter create hello_world -t app
  cd hello_world
  flutter run -d desktop-auto
  ```

---

## Running the `dart_pdf` Demo

```sh
./flutter_workspace.py --enable=pdfium
source ./setup_env.sh
export LD_LIBRARY_PATH=${FLUTTER_WORKSPACE}/app/pdfium/pdfium/out/Linux-Release/
pushd app/dart_pdf/demo
flutter run -d desktop-homescreen
```

---

## Working with LLVM

### Set the Preferred LLVM Toolchain

To specify the LLVM toolchain version:

```sh
PREFER_LLVM=10 ./flutter_workspace.py
```

- If `PREFER_LLVM` is set, it overrides `clang-stable`.
- The first matching `llvm-config-<number>` in `/usr` is selected.

### List Available LLVM Installs

```sh
find /usr -type f -executable -name 'llvm-config*'
```

---

## Visual Studio Code Integration

### Launching on Ubuntu

```sh
cd <your flutter workspace>
source ./setup_env.sh
code .
```

### Debugging with VS Code

- `flutter_workspace.py` creates a `.vscode/launch.json` if not present.
- Uses the `pubspec_path` key from repo JSON to add entries to `launch.json`.
- Supports debugging for configured repositories.

