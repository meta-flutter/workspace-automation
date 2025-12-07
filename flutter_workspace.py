#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: (C) 2020-2025 workspace-automation contributors
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Script that creates a Flutter Workspace
#
# A Flutter Workspace includes:
#
#   .config/flutter
#   .config/flutter_workspace
#   .config/flutter_workspace/pub_cache
#   .config/flutter_workspace/flutter-engine
#   .config/flutter_workspace/<platform id>
#   .vscode
#   app
#   flutter
#   setup_env.sh
#
#
# One runs this script to create the workspace, then from working terminal
# set up the environment:
#
# "source ./setup_env.sh" or ". ./setup_env.sh"
#
# if QEMU image is loaded type `run-<platform id>` to run QEMU image
#

import argparse
import io
import json
import os
import platform
import shlex
import shutil
import signal
import subprocess
import stat
import string
import sys
import time
import zipfile

from pathlib import Path
from platform import system
from shlex import quote as shlex_quote
from typing import Dict, List, Optional, Tuple

from common import check_python_version
from common import chown_workspace
from common import compare_sha256
from common import download_https_file
from common import fetch_https_binary_file
from common import get_flutter_arch
from common import get_host_machine_arch
from common import get_ws_folder
from common import handle_ctrl_c
from common import print_banner
from common import reset_sudo_timestamp
from common import validate_sudo_user
from common import validate_sudo_user_timestamp

from create_aot import create_platform_aot
from create_aot import get_flutter_sdk_version

# Map of _BUILD_TYPE values to CMAKE_BUILD_TYPE
build_types_cmake = {
    'debug': 'Debug',
    'profile': 'RelWithDebInfo',
    'release': 'Release'
}

# Map of _BUILD_TYPE values to MESON_BUILD_TYPE
build_types_meson = {
    'debug': 'debug',
    'profile': 'releasewithdebuginfo',
    'release': 'release'
}

# map of config names to build types
# (if not specified, defaults to globals' _BUILD_TYPE)
build_types = {}

# `configs/globals.json` values
globals_ = {}


def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return


def main():
    global globals_
    
    check_python_version()

    parser = argparse.ArgumentParser()
    parser.add_argument('--clean', default=False,
                        action='store_true', help='Wipes workspace clean')
    parser.add_argument('--config', default='configs', type=str,
                        help='Selects custom workspace configuration folder')
    parser.add_argument('--flutter-version', default='', type=str,
                        help='Select flutter version.  Overrides config file key:'
                             ' flutter_version')
    parser.add_argument('--github-token', default='', type=str,
                        help='Set github-token.  Overrides _globals.json key/value')
    parser.add_argument('--cookie-file', default='', type=str,
                        help='Set cookie-file to use.  Overrides _globals.json key/value')
    parser.add_argument('--fetch-engine', default=False,
                        action='store_true', help='Fetch Engine artifacts')
    parser.add_argument('--find-working-commit', default=False, action='store_true',
                        help='Use to finding GIT commit where flutter analyze returns true')
    parser.add_argument('--plex', default='', type=str, help='Platform Load Excludes')
    parser.add_argument('--enable', default='', type=str, help='Platform Load Enable Override')
    parser.add_argument('--disable', default='', type=str, help='Platform Load Disable Override')
    parser.add_argument('--enable-plugin', default='', type=str, help='Plugin Enable')
    parser.add_argument('--disable-plugin', default='', type=str, help='Plugin Disable')
    parser.add_argument('--fastboot', default='', type=str, help='Update the selected platform using fastboot')
    parser.add_argument('--mask-rom', default='', type=str, help='Update the selected platform using Mask ROM')
    parser.add_argument('--device-id', default='', type=str, help='device id for flashing')

    parser.add_argument('--stdin-file', default='', type=str, help='Use for passing stdin for debugging')
    parser.add_argument('--plugin-platform', default='linux', type=str, help='specify plugin platform type')
    parser.add_argument('--create-aot', default=False, action='store_true', help='Generate AOT')
    parser.add_argument('--app-path', default='', type=str, help='Specify Application path')
    parser.add_argument('--copy-dconf-user', default=False, action='store_true',
                        help='copy $HOME/.confi/dconf/user to $FLUTTER_WORKSPACE')
    parser.add_argument('--build-type', default='', type=str,
                        help='Specify build types.  Format: <platform_id>:<build_type>,<platform_id>:<build_type>.  '
                             'Valid build types are debug, profile, release.  '
                             'If not specified, defaults to globals\' _BUILD_TYPE')

    args = parser.parse_args()

    print(f'Arguments {args}')

    # Check if running in CI
    is_ci = os.environ.get('CI') == 'true'

    #
    # Generate Release/Profile AOT
    #
    if args.create_aot:
        if args.build_type != '':
            # if create_aot is specified then build_type will be ignored
            print("WARNING: --build-type is ignored when --create-aot is specified")

        if args.app_path == '':
            print("Must specify value for --app-path")
            sys.exit(1)

        activate_python_venv()
        set_gen_snapshot('release', get_flutter_arch())
        create_platform_aot(args.app_path, get_flutter_sdk_version())
        return

    #
    # Specify build types
    #
    if not args.create_aot and args.build_type != '':
        # format: --build-type <platform_id>:<build_type>,<platform_id>:<build_type>
        build_type_list = args.build_type.split(',')

        for build_type in build_type_list:
            platform_id, build_type = build_type.split(':')
            build_types[platform_id] = build_type
            if build_type not in build_types_cmake:
                # print warning and ignore
                print(f"WARNING: Invalid build type '{build_type}' specified for platform '{platform_id}'")
                del build_types[platform_id]

        print(f"Build types: {build_types}")

    #
    # Copy dconf user to workspace
    #
    if args.copy_dconf_user:
        copy_dconf_user()
        return

    #
    # Find GIT Commit where `flutter analyze` returns true
    #
    if args.find_working_commit:
        flutter_analyze_git_commits()
        return

    user = get_process_stdout('whoami').split('\n')
    username = user[0]
    print_banner("Running as: %s" % username)
    # we need to know the user running the script
    if username == 'root':
        print("Please run as non-root user")
        exit()

    #
    # Handle sudo for scenarios that require it
    #
    reset_sudo_timestamp()

    validate_sudo_user_timestamp(args)

    #
    # Target Folder
    #
    workspace = get_ws_folder()
    config_folder = os.path.join(workspace, '.config')

    print_banner("Setting up Flutter Workspace in: %s" % workspace)

    #
    # Recursively change ownership to logged-in user
    #
    chown_workspace(username, workspace)

    #
    # Install minimum package
    #
    install_minimum_runtime_deps()

    #
    # Create Workspace
    #
    os.makedirs(workspace, exist_ok=True)

    if os.path.exists(workspace):
        os.environ['FLUTTER_WORKSPACE'] = workspace

    #
    # Fetch Engine Artifacts
    #
    if args.fetch_engine:
        print_banner("Fetching Engine Artifacts")
        get_flutter_engine_runtime(True, get_flutter_arch())
        return

    #
    # Limit compiler threads
    #

    # (non-CI only)
    # decide a number of threads to use for compilation
    # assuming each core needs at least 1GB of RAM
    # meaning max_threads = min(num_cores, floor(total_ram_in_GB))
    sys_core_count = os.cpu_count()
    
    #if linux
    if sys.platform.startswith('linux'):
        sys_ram_gb = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / (1024. ** 3) # in GB
    # if windows
    elif sys.platform.startswith('win'):
        # execute `systeminfo | findstr /C:"Total Physical Memory"` 
        cmd = ['systeminfo']
        output = subprocess.check_output(cmd, shell=True, text=True)
        for line in output.splitlines():
            if "Total Physical Memory" in line:
                parts = line.split(":")
                if len(parts) == 2:
                    mem_str = parts[1].strip()
                    # remove commas and "MB" or "GB"
                    mem_str = mem_str.replace(",", "").replace("MB", "").replace("GB", "").strip()
                    try:
                        mem_value = float(mem_str)
                        if "MB" in parts[1]:
                            sys_ram_gb = mem_value / 1024  # convert MB to GB
                        else:
                            sys_ram_gb = mem_value  # already in GB
                    except ValueError:
                        sys_ram_gb = 0
                break
    # if macos
    elif sys.platform.startswith('darwin'):
        cmd = ['sysctl', 'hw.memsize']
        output = subprocess.check_output(cmd, text=True)
        parts = output.split(":")
        if len(parts) == 2:
            try:
                mem_bytes = int(parts[1].strip())
                sys_ram_gb = mem_bytes / (1024. ** 3)  # convert bytes to GB
            except ValueError:
                sys_ram_gb = 0
    else:
        sys_ram_gb = 0

    sys_ram_gb -= 1  # leave 1GB for system

    # if CI=false or not set
    if sys_core_count and sys_ram_gb and not is_ci:
        max_threads = int(min(sys_core_count, sys_ram_gb))
    elif sys_core_count:
        max_threads = int(sys_core_count)
    else:
        max_threads = 1

    max_threads = max(1, max_threads)  # ensure at least 1 thread

    os.environ['_MAX_THREADS'] = str(max_threads)
    print("Using %s threads for compilation" % os.environ.get('_MAX_THREADS'))

    #
    # Workspace Configuration
    #
    configs, globals_config, flutter_version = load_configs(
        Path(args.config),
        args.flutter_version,
        args.enable,
        args.disable
    )

    print(f"\nResolved Flutter version: {flutter_version}")
    print(f"Loaded {len(configs)} configs")
    print(f'Enabled Configs')
    for c in configs:
        if c.get('load', True):
            print(f" - {c.get('id', 'unknown')}")

    os.environ['FLUTTER_VERSION'] = flutter_version
    globals_ = globals_config

    handle_build_type(os.environ, globals_config.get('build_type'))

    # allow max threads override from globals.json
    if '_MAX_THREADS' in globals_config:
        os.environ['_MAX_THREADS'] = globals_config.get('_MAX_THREADS', str(max_threads))

    for c in configs:
        if not validate_platform_config(c):
            print("Invalid platform configuration")
            exit(1)

    app_folder = os.path.join(workspace, 'app')
    flutter_sdk_folder = os.path.join(workspace, 'flutter')

    vscode_folder = os.path.join(workspace, '.vscode')

    clean_workspace = False
    if args.clean:
        clean_workspace = args.clean
        if clean_workspace:
            print_banner("Cleaning Workspace")

    if clean_workspace:

        try:
            os.remove(os.path.join(workspace, 'setup_env.sh'))
        except FileNotFoundError:
            pass

        try:
            os.remove(os.path.join(workspace, 'qemu_run.scpt'))
        except FileNotFoundError:
            pass

        clear_folder(config_folder)

        clear_folder(app_folder)
        clear_folder(flutter_sdk_folder)

        clear_folder(vscode_folder)

    #
    # Fast Boot
    #
    if args.fastboot:
        print_banner("Fastboot Flash")
        flash_fastboot(args.fastboot, args.device_id, configs)
        return

    #
    # Mask ROM
    #
    if args.mask_rom:
        flash_mask_rom(args.mask_rom, args.device_id, configs)
        return

    #
    # App folder setup
    #
    is_exist = os.path.exists(app_folder)
    if not is_exist:
        os.makedirs(app_folder)

    get_workspace_repos(app_folder, configs)

    #
    # Prepend depot_tools to PATH
    #
    depot_tools_path = os.path.join(workspace, 'app', 'depot_tools')
    os.environ['PATH'] = f"{depot_tools_path}{os.pathsep}{os.environ.get('PATH')}"

    #
    # Get Flutter SDK
    #

    print_banner("Flutter Version: %s" % flutter_version)
    flutter_sdk_path = get_flutter_sdk(flutter_version)
    flutter_bin_path = os.path.join(flutter_sdk_path, 'bin')

    # force tool rebuild
    force_tool_rebuild(flutter_sdk_folder)

    # Enable custom devices in dev and stable
    if flutter_version != "main":
        patch_flutter_sdk(flutter_sdk_folder)

    #
    # Configure Workspace
    #

    os.environ['PATH'] = f"{flutter_bin_path}{os.pathsep}{os.environ.get('PATH')}"
    print("PATH=%s" % os.environ.get('PATH'))

    os.environ['PUB_CACHE'] = os.path.join(os.environ.get('FLUTTER_WORKSPACE'), '.config', 'flutter_workspace',
                                           'pub_cache')
    print("PUB_CACHE=%s" % os.environ.get('PUB_CACHE'))

    if sys.platform.startswith('win'):
        os.environ['GCLIENT'] = 'gclient.bat'
        os.environ['AUTONINJA'] = 'autoninja.bat'
        os.environ['NINJA'] = 'ninja.bat'
        os.environ['GN'] = 'gn.bat'
        os.environ['REMOVE_TREE'] = 'rmdir /s /q'
        os.environ['MAKE_DIR'] = 'mkdir'
        os.environ['COPY'] = 'copy'
        os.environ['RET_TRUE'] = '2>nul'
        print("APPDATA=%s" % os.environ.get('APPDATA'))
    else:
        os.environ['GCLIENT'] = 'gclient'
        os.environ['AUTONINJA'] = 'autoninja'
        os.environ['NINJA'] = 'ninja'
        os.environ['GN'] = 'gn'
        os.environ['REMOVE_TREE'] = 'rm -rf'
        os.environ['MAKE_DIR'] = 'mkdir -p'
        os.environ['COPY'] = 'cp'
        os.environ['RET_TRUE'] = '|true'
        os.environ['XDG_CONFIG_HOME'] = os.path.join(
            os.environ.get('FLUTTER_WORKSPACE'), '.config', 'flutter')
        print("XDG_CONFIG_HOME=%s" % os.environ.get('XDG_CONFIG_HOME'))

    #
    # Trigger upgrade on Channel if `version` is all letters
    #
    if flutter_version.isalpha():
        print_banner("Setting channel to `%s`" % flutter_version)
        cmd = ['flutter', 'channel', flutter_version]
        subprocess.check_call(cmd, cwd=flutter_sdk_path)
        print_banner("Upgrading")
        cmd = ['flutter', 'upgrade', '--force']
        subprocess.check_call(cmd, cwd=flutter_sdk_path)

    #
    # Configure SDK
    #
    configure_flutter_sdk()

    #
    # Flutter Engine Runtime
    #
    get_flutter_engine_runtime(clean_workspace, get_flutter_arch())

    #
    # Setup Platform(s)
    #
    github_token = globals_.get('github_token')
    if args.github_token:
        github_token = args.github_token

    cookie_file = globals_.get('cookie_file')
    if args.cookie_file:
        cookie_file = args.cookie_file

    #
    # Write environmental script header
    #
    write_env_script_header(workspace)

    #
    # Append GEN_SNAPSHOT to environment script
    #
    if sys.platform.startswith('win'):
        append_to_env_script(workspace, '$env:FLUTTER_ENGINE_VERSION="${FLUTTER_ENGINE_VERSION}"')
        append_to_env_script(workspace, '$env:HOST_ARCH_GOOGLE="${HOST_ARCH_GOOGLE}"')
        append_to_env_script(workspace, '$env:GEN_SNAPSHOT="$FLUTTER_WORKSPACE/.config/flutter_workspace/flutter-engine/$FLUTTER_ENGINE_VERSION/engine-sdk-release-$HOST_ARCH_GOOGLE/flutter/engine/src/out/linux_release_$HOST_ARCH_GOOGLE/engine-sdk/bin/gen_snapshot"')
    else:
        append_to_env_script(workspace, 'export FLUTTER_ENGINE_VERSION="${FLUTTER_ENGINE_VERSION}"')
        append_to_env_script(workspace, 'export HOST_ARCH_GOOGLE="${HOST_ARCH_GOOGLE}"')
        append_to_env_script(workspace, 'export GEN_SNAPSHOT="$FLUTTER_WORKSPACE/.config/flutter_workspace/flutter-engine/$FLUTTER_ENGINE_VERSION/engine-sdk-release-$HOST_ARCH_GOOGLE/flutter/engine/src/out/linux_release_$HOST_ARCH_GOOGLE/engine-sdk/bin/gen_snapshot"')

    #
    # Setup Platforms
    #
    setup_platforms(configs, github_token, cookie_file, args.plex, args.enable, args.disable, args.enable_plugin,
                    args.disable_plugin, app_folder)

    #
    # Write environmental script footer
    #
    write_env_script_footer(workspace)

    #
    # Display the custom devices list
    #
    if flutter_version == "main":
        cmd = ['flutter', 'custom-devices', 'list']
        subprocess.check_call(cmd)

    #
    # Recursively change ownership to logged-in user
    #
    chown_workspace(username, workspace)

    #
    # Done
    #
    print_banner("Setup Flutter Workspace - Complete")


def clear_folder(dir_):
    """ Clears folder specified """
    if os.path.exists(dir_):
        shutil.rmtree(dir_)


def copy_dconf_user():
    """ Copies $HOME/.config/dconf/user to workspace """
    from pathlib import Path

    workspace = Path(os.environ.get('FLUTTER_WORKSPACE'))
    dconf_dst = workspace.joinpath('.config', 'flutter', 'dconf')
    os.makedirs(dconf_dst, exist_ok=True)

    workspace = Path(os.environ.get('FLUTTER_WORKSPACE'))
    dconf_user_src = os.path.join(os.environ.get('HOME'), '.config', 'dconf', 'user')
    dconf_user_dst = workspace.joinpath('.config', 'flutter', 'dconf', 'user')

    print(f'Copying {dconf_user_src} to {dconf_user_dst}')
    shutil.copy(dconf_user_src, dconf_user_dst)
    print_banner('Copied')


def load_json_config(path: Path) -> Dict:
    """Load JSON config file."""
    print(f"Loading config file: {path}")
    with open(path, 'r') as f:
        return json.load(f)


def validate_flutter_versions(configs: List[Dict], globals_config: Dict, flutter_version_override: str = '') -> str:
    """
    Validate Flutter version dependencies across enabled configs.

    Returns:
        The resolved Flutter version to use.

    Exits:
        If multiple conflicting versions are specified.
    """
    # Collect all specified Flutter versions from enabled configs
    config_versions = set()
    for config in configs:
        if not isinstance(config, dict):
            continue
        if not config.get('load', False):
            continue
        version = config.get('flutter_version')
        if version:
            config_versions.add(version)

    # Master override from command line
    if flutter_version_override:
        print(f"Using Flutter version override from command line: {flutter_version_override}")

        # Check default version from globals
        default_version = globals_config.get('flutter_version')
        if default_version and default_version != flutter_version_override:
            print(f"WARNING: Command-line override '{flutter_version_override}' differs from globals.json default '{default_version}'")

        # Check enabled config versions - FAIL if they don't match override
        if config_versions:
            for version in config_versions:
                if version != flutter_version_override:
                    print(f"ERROR: Command-line override '{flutter_version_override}' conflicts with enabled config version '{version}'")
                    print("\nEnabled configs:")
                    for config in configs:
                        if isinstance(config, dict) and config.get('load', False) and config.get('flutter_version'):
                            print(f"  - {config.get('id', 'unknown')}: {config['flutter_version']}")
                    sys.exit(1)

        return flutter_version_override

    default_version = globals_config.get('flutter_version')
    if not default_version:
        print("ERROR: No flutter_version defined in configs/globals.json")
        sys.exit(1)

    # No versions specified - use default
    if not config_versions:
        print(f"Using default Flutter version from globals.json: {default_version}")
        return default_version

    # Single version specified - use it
    if len(config_versions) == 1:
        version = list(config_versions)[0]
        if version != default_version:
            print(f"NOTE: Using Flutter version '{version}' from enabled config (differs from globals.json default '{default_version}')")
        else:
            print(f"Using Flutter version from config: {version}")
        return version

    # Multiple conflicting versions - error
    print("ERROR: Multiple conflicting Flutter versions specified in enabled configs:")
    for config in configs:
        if isinstance(config, dict) and config.get('load', False) and config.get('flutter_version'):
            print(f"  - {config.get('id', 'unknown')}: {config['flutter_version']}")
    print("\nAll enabled configs must use the same Flutter version.")
    sys.exit(1)


def load_configs(config_dir: Path, flutter_version_override: str = '', enable: str = '', disable: str = '') -> Tuple[List[Dict], Dict, str]:
    """
    Load all configs and validate Flutter version.

    Args:
        config_dir: Path to configs directory
        flutter_version_override: Master override for Flutter version (from command line)
        enable: Comma-separated list of platform IDs to enable
        disable: Comma-separated list of platform IDs to disable

    Returns:
        Tuple of (configs_list, globals_config, resolved_flutter_version)
    """
    # Load globals
    globals_path = config_dir / "globals.json"
    if not globals_path.exists():
        print(f"ERROR: globals.json not found at {globals_path}")
        sys.exit(1)

    globals_config = load_json_config(globals_path)

    # Parse enable/disable lists
    enable_list = enable.split(',') if enable else []
    disable_list = disable.split(',') if disable else []

    # Files to skip (not platform configs)
    skip_files = {'globals.json', 'repos.json'}

    # Load all platform config files (excluding globals.json and repos.json)
    configs = []
    for config_file in sorted(config_dir.glob("*.json")):
        if config_file.name in skip_files:
            continue
        config = load_json_config(config_file)
        if isinstance(config, dict):
            platform_id = config.get('id')

            # Apply enable/disable overrides
            if platform_id in enable_list:
                config['load'] = True
            elif platform_id in disable_list:
                config['load'] = False

            configs.append(config)
        else:
            print(f"WARNING: {config_file} did not load as a dict, skipping")

    # Validate Flutter versions with override
    flutter_version = validate_flutter_versions(configs, globals_config, flutter_version_override)

    return configs, globals_config, flutter_version


def get_workspace_config(path):
    """ Returns workspace config """

    data = {'globals': None, 'repos': None, 'platforms': []}

    if os.path.isdir(path):

        import glob
        for filename in sorted(glob.glob(os.path.join(path, '*.json'))):

            filepath = os.path.join(os.getcwd(), filename)
            with open(filepath, 'r', encoding="utf-8") as f:

                _, tail = os.path.split(filename)

                if tail == 'repos.json':
                    try:
                        data['repos'] = json.load(f)
                    except json.decoder.JSONDecodeError:
                        print("Invalid JSON in %s" % f)
                        exit(1)

                elif tail == 'globals.json':
                    try:
                        data['globals'] = json.load(f)
                    except json.decoder.JSONDecodeError:
                        print("Invalid JSON in %s" % f)
                        exit(1)

                else:
                    print_banner(f'Loading: {filepath}')
                    try:
                        platform_ = json.load(f)
                        data['platforms'].append(platform_)
                    except json.decoder.JSONDecodeError:
                        print("Invalid JSON in %s" % f)
                        exit(1)

    elif os.path.isfile(path):
        with open(path, 'r', encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.decoder.JSONDecodeError:
                print("Invalid JSON in %s" % f)
                exit(1)

    return data


def validate_platform_config(platform_):
    """ Validates Platform Configuration returning bool """

    if 'id' not in platform_:
        print_banner("Missing 'id' key in platform config")
        return False
    if 'load' not in platform_:
        print_banner("Missing 'load' key in platform config")
        return False
    if 'supported_archs' not in platform_:
        print_banner("Missing 'supported_archs' key in platform config")
        return False
    if 'supported_host_types' not in platform_:
        print_banner("Missing 'supported_host_types' key in platform config")
        return False
    if 'type' not in platform_:
        print_banner("Missing 'type' key in platform config")
        return False
    else:
        if platform_['type'] == 'generic':
            if 'runtime' not in platform_:
                print_banner("Missing 'runtime' key in platform config")
                return False

        elif platform_['type'] == 'dependency':
            if 'runtime' not in platform_:
                print_banner("Missing 'runtime' key in platform config")
                return False

        elif platform_['type'] == 'toolchain':
            if 'runtime' not in platform_:
                print_banner("Missing 'runtime' key in platform config")
                return False

        elif platform_['type'] == 'qemu':
            if 'runtime' not in platform_:
                print_banner("Missing 'runtime' key in platform config")
                return False
            if 'custom-device' not in platform_:
                print_banner("Missing 'custom-device' key in platform config")
                return False
            if 'config' not in platform_['runtime']:
                print_banner("Missing 'config' key in platform config")
                return False
            if 'artifacts' not in platform_['runtime']:
                print_banner("Missing 'artifacts' key in platform config")
                return False
            if 'qemu' not in platform_['runtime']:
                print_banner("Missing 'qemu' key in platform config")
                return False

        elif platform_['type'] == 'docker':
            if 'runtime' not in platform_:
                print_banner("Missing 'runtime' key in platform config")
                return False
            if 'custom-device' not in platform_:
                print_banner("Missing 'custom-device' key in platform config")
                return False
            if 'overwrite-existing' not in platform_:
                print_banner(
                    "Missing 'overwrite-existing' key in platform config")
                return False

        elif platform_['type'] == 'host':
            if 'runtime' not in platform_:
                print_banner("Missing 'runtime' key in platform config")
                return False
            if 'custom-device' not in platform_:
                print_banner("Missing 'custom-device' key in platform config")
                return False
            if 'overwrite-existing' not in platform_:
                print_banner(
                    "Missing 'overwrite-existing' key in platform config")
                return False

        elif platform_['type'] == 'remote':
            if 'runtime' not in platform_:
                print_banner("Missing 'runtime' key in platform config")
                return False
            if 'custom-device' not in platform_:
                print_banner("Missing 'custom-device' key in platform config")
                return False
            if 'overwrite-existing' not in platform_:
                print_banner(
                    "Missing 'overwrite-existing' key in platform config")
                return False

        else:
            print("platform type %s is not currently supported." %
                  (platform_['type']))
            return False

    return True


def validate_custom_device_config(config):
    """ Validates custom-device Configuration returning bool """

    if 'id' not in config:
        print_banner("Missing 'id' key in custom-device config")
        return False
    if 'label' not in config:
        print_banner("Missing 'label' key in custom-device config")
        return False
    if 'sdkNameAndVersion' not in config:
        print_banner("Missing 'sdkNameAndVersion' key in custom-device config")
        return False
    if 'platform' not in config:
        print_banner("Missing 'platform' key in custom-device config")
        return False
    if 'enabled' not in config:
        print_banner("Missing 'enabled' key in custom-device config")
        return False
    if 'ping' not in config:
        print_banner("Missing 'ping' key in custom-device config")
        return False
    if 'pingSuccessRegex' not in config:
        print_banner("Missing 'pingSuccessRegex' key in custom-device config")
        return False
    if 'postBuild' not in config:
        print_banner("Missing 'postBuild' key in custom-device config")
        return False
    if 'install' not in config:
        print_banner("Missing 'install' key in custom-device config")
        return False
    if 'uninstall' not in config:
        print_banner("Missing 'uninstall' key in custom-device config")
        return False
    if 'runDebug' not in config:
        print_banner("Missing 'runDebug' key in custom-device config")
        return False
    if 'forwardPort' not in config:
        print_banner("Missing 'forwardPort' key in custom-device config")
        return False
    if 'forwardPortSuccessRegex' not in config:
        print_banner(
            "Missing 'forwardPortSuccessRegex' key in custom-device config")
        return False
    if 'screenshot' not in config:
        print_banner("Missing 'screenshot' key in custom-device config")
        return False

    return True


def get_repo(base_folder, uri, branch, rev):
    """ Clone Git Repo """
    if not uri:
        print("repo entry needs a 'uri' key.  Skipping")
        return
    if not branch:
        print("repo entry needs a 'branch' key.  Skipping")
        return

    # get repo folder name
    repo_name = uri.rsplit('/', 1)[-1]
    repo_name = repo_name.split(".")
    repo_name = repo_name[0]

    print_banner(f'Fetching: {repo_name}')

    git_folder = str(os.path.join(base_folder, repo_name))
    git_hidden_folder = os.path.join(git_folder, '.git')

    # print_banner(f'Checking if file exists: {git_hidden_folder}')
    if os.path.exists(git_hidden_folder):
        # print_banner(f'git reset --hard: {repo_name}')
        cmd = ['git', 'reset', '--hard']
        subprocess.check_call(cmd, cwd=git_folder)

        # print_banner(f'git fetch --all: {repo_name}')
        cmd = ['git', 'fetch', '--all']
        subprocess.check_call(cmd, cwd=git_folder)

        # print_banner(f'git pull: {repo_name}')
        cmd = ['git', 'pull', 'origin', branch]
        subprocess.check_call(cmd, cwd=git_folder)
    else:
        # print_banner(f'Checking if folder exists: {git_folder}')
        if os.path.exists(git_folder):
            try:
                subprocess.run(['rm', '-rf', git_folder], cwd=base_folder, check=True)
            except subprocess.CalledProcessError:
                pass

        # print_banner(f'git clone {uri} -b {branch} {repo_name}')
        cmd = ['git', 'clone', uri, '-b', branch, repo_name]
        subprocess.check_call(cmd, cwd=base_folder)

    if rev:
        # print_banner(f'git checkout {rev}')
        cmd = ['git', 'checkout', rev]
        subprocess.check_call(cmd, cwd=git_folder)
    else:
        # print_banner(f'git checkout {branch}')
        cmd = ['git', 'checkout', branch]
        subprocess.check_call(cmd, cwd=git_folder)

    # get lfs
    git_lfs_file = os.path.join(base_folder, repo_name, '.gitattributes')
    # print_banner(f'Checking if folder exists: {git_lfs_file}')
    if os.path.exists(git_lfs_file):
        # print_banner(f'Fetching LFS: {repo_name}')
        cmd = ['git', 'lfs', 'fetch', '--all']
        subprocess.check_call(cmd, cwd=git_folder)

    # get all submodules
    git_submodule_file = os.path.join(base_folder, repo_name, '.gitmodules')
    # print_banner(f'Checking if folder exists: {git_submodule_file}')
    if os.path.exists(git_submodule_file):
        # print_banner(f'Fetching submodules: {repo_name}')
        cmd = ['git', 'submodule', 'update', '--init', '--recursive']
        subprocess.check_call(cmd, cwd=git_folder)

    print_banner(f'Fetched: {repo_name}')


def get_workspace_repos(base_folder, config):
    """ Clone GIT repos referenced in config repos dict to base_folder """
    import concurrent.futures

    if 'repos' not in config:
        return

    repos = config['repos']

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for repo in repos:
            futures.append(executor.submit(get_repo, base_folder=base_folder, uri=repo.get(
                'uri'), branch=repo.get('branch'), rev=repo.get('rev')))
            validate_sudo_user()

        for _ in concurrent.futures.as_completed(futures):
            validate_sudo_user()

    print_banner("Repos Cloned")

    # reset sudo timeout
    validate_sudo_user()

    #
    # Create vscode startup tasks
    #
    platform_ids = get_platform_ids(config.get('platforms'))
    create_vscode_launch_file(repos, platform_ids)


def get_platform_ids(platforms: dict) -> list:
    res = []
    for platform_ in platforms:
        res.append(platform_['id'])
    return res


def get_platform_src(src, base_folder: str):
    if src is None:
        return

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for repo in src:
            futures.append(executor.submit(get_repo, base_folder=base_folder, uri=repo.get(
                'uri'), branch=repo.get('branch'), rev=repo.get('rev')))
            validate_sudo_user()

        for future in concurrent.futures.as_completed(futures):
            future.result()  # Get result to propagate any exceptions
            validate_sudo_user()

    print_banner("Source Repos Cloned")

    validate_sudo_user()


def get_flutter_settings_folder():
    """ Returns the path where .flutter_settings should be stored """
    if sys.platform.startswith('win'):
        appdata = os.environ.get('APPDATA')
        if appdata:
            return os.path.join(appdata, 'flutter')
        else:
            print_banner("APPDATA is not set.")
            exit(1)
    elif "XDG_CONFIG_HOME" in os.environ:
        settings_folder = os.path.join(os.environ.get('XDG_CONFIG_HOME'))
    else:
        settings_folder = os.path.join(os.environ.get('HOME'), '.config', 'flutter')

    os.makedirs(settings_folder, exist_ok=True)
    return settings_folder


def get_flutter_custom_config_path():
    """ Returns the path of the Flutter Custom Config JSON file """

    folder = get_flutter_settings_folder()
    # print("folder: %s" % folder)
    if sys.platform.startswith('win'):
        return os.path.join(folder, '.flutter_custom_devices.json')
    
    return os.path.join(folder, 'custom_devices.json')


def get_flutter_custom_devices():
    """ Returns the Flutter custom_devices.json as dict """

    custom_config = get_flutter_custom_config_path()
    if os.path.exists(custom_config):

        f = open(custom_config, encoding="utf-8")
        try:
            data = json.load(f)
        except json.decoder.JSONDecodeError:
            # in case JSON is invalid
            print("Invalid JSON in %s" % custom_config)
            exit(1)
        f.close()

        if 'custom-devices' in data:
            return data['custom-devices']

    print("%s not present in filesystem." % custom_config)

    return {}


def remove_flutter_custom_devices_id(id_):
    """ Removes Flutter custom devices that match given id from the
    configuration file """

    # print("Removing custom-device with ID: %s" % id_)
    custom_config = get_flutter_custom_config_path()
    if os.path.exists(custom_config):

        f = open(custom_config, "r", encoding="utf-8")
        try:
            obj = json.load(f)
        except json.decoder.JSONDecodeError:
            print_banner("Invalid JSON in %s" %
                         custom_config)  # in case JSON is invalid
            exit(1)
        f.close()

        new_device_list = []
        if 'custom-devices' in obj:
            devices = obj['custom-devices']
            for device in devices:
                if 'id' in device and id_ != device['id']:
                    new_device_list.append(device)

        custom_devices = {'custom-devices': new_device_list}

        if 'custom-devices' not in custom_devices:
            print("Removing empty file: %s" % custom_config)
            os.remove(custom_config)
            return

        with open(custom_config, "w", encoding="utf-8") as file:
            json.dump(custom_devices, file, indent=2)

    return


def patch_string_array(find_token, replace_token, list_):
    return [w.replace(find_token, replace_token) for w in list_]


def patch_custom_device_strings(devices, flutter_runtime):
    """ Patch custom device string environmental variables to use literal
    values """

    workspace = os.getenv('FLUTTER_WORKSPACE')
    bundle_folder = os.getenv('BUNDLE_FOLDER')
    host_arch = get_host_machine_arch()

    for device in devices:

        str_token = '${FLUTTER_WORKSPACE}'

        if device.get('label'):
            if '${MACHINE_ARCH}' in device['label']:
                device['label'] = device['label'].replace(
                    '${MACHINE_ARCH}', host_arch)

        if device.get('platform'):
            if host_arch == 'x86_64':
                device['platform'] = 'linux-x64'
            elif host_arch == 'arm64':
                device['platform'] = 'linux-arm64'

        if device.get('sdkNameAndVersion'):

            if '${FLUTTER_RUNTIME}' in device['sdkNameAndVersion']:
                sdk_name_and_version = device['sdkNameAndVersion'].replace(
                    '${FLUTTER_RUNTIME}', flutter_runtime)
                device['sdkNameAndVersion'] = sdk_name_and_version

            if '${MACHINE_ARCH_HYPHEN}' in device['sdkNameAndVersion']:
                device['sdkNameAndVersion'] = device['sdkNameAndVersion'].replace('${MACHINE_ARCH_HYPHEN}',
                                                                                  host_arch.replace('_', '-'))

        if device.get('postBuild'):
            device['postBuild'] = patch_string_array(
                str_token, workspace, device['postBuild'])

        if device.get('runDebug'):
            device['runDebug'] = patch_string_array(
                str_token, workspace, device['runDebug'])

        str_token = '${BUNDLE_FOLDER}'
        if device.get('install'):
            device['install'] = patch_string_array(
                str_token, bundle_folder, device['install'])

    return devices


def fixup_custom_device(obj):
    """ Patch custom device string environmental variables to use literal values """

    is_posix = not sys.platform.startswith('win')
    obj['id'] = os.path.expandvars(obj['id'])
    obj['label'] = os.path.expandvars(obj['label'])
    obj['sdkNameAndVersion'] = os.path.expandvars(obj['sdkNameAndVersion'])
    obj['platform'] = os.path.expandvars(obj['platform'])
    obj['ping'] = os.path.expandvars(obj['ping'])
    obj['ping'] = shlex.split(obj['ping'], posix=is_posix)
    obj['pingSuccessRegex'] = os.path.expandvars(obj['pingSuccessRegex'])
    if obj['postBuild']:
        obj['postBuild'] = os.path.expandvars(obj['postBuild'])
        obj['postBuild'] = shlex.split(obj['postBuild'], posix=is_posix)
    if obj['install']:
        obj['install'] = os.path.expandvars(obj['install'])
        obj['install'] = shlex.split(obj['install'], posix=is_posix)
    if obj['uninstall']:
        obj['uninstall'] = os.path.expandvars(obj['uninstall'])
        obj['uninstall'] = shlex.split(obj['uninstall'], posix=is_posix)
    if obj['runDebug']:
        obj['runDebug'] = os.path.expandvars(obj['runDebug'])
        obj['runDebug'] = shlex.split(obj['runDebug'], posix=is_posix)
    if obj['forwardPort']:
        obj['forwardPort'] = os.path.expandvars(obj['forwardPort'])
        obj['forwardPort'] = shlex.split(obj['forwardPort'], posix=is_posix)
    if obj['forwardPortSuccessRegex']:
        obj['forwardPortSuccessRegex'] = os.path.expandvars(
            obj['forwardPortSuccessRegex'])
    if obj['screenshot']:
        obj['screenshot'] = os.path.expandvars(obj['screenshot'])
        obj['screenshot'] = shlex.split(obj['screenshot'], posix=is_posix)

    return obj


def add_flutter_custom_device(device_config, flutter_runtime):
    """ Add a single Flutter custom device from JSON string """

    if not validate_custom_device_config(device_config):
        exit(1)

    # print("Adding custom-device: %s" % device_config)

    custom_devices_file = get_flutter_custom_config_path()

    new_device_list = []
    if os.path.exists(custom_devices_file):

        f = open(custom_devices_file, "r", encoding="utf-8")
        try:
            obj = json.load(f)
        except json.decoder.JSONDecodeError as e:
            print_banner(f"Invalid JSON in {custom_devices_file}: {str(e)}")
            sys.exit(1)
        f.close()

        id_ = device_config['id']

        if 'custom-devices' in obj:
            devices = obj['custom-devices']
            for device in devices:
                if 'id' in device and id_ != device['id']:
                    new_device_list.append(device)

    new_device_list.append(device_config)
    patched_device_list = patch_custom_device_strings(
        new_device_list, flutter_runtime)

    custom_devices = {'custom-devices': patched_device_list}

    print("custom_devices_file: %s" % custom_devices_file)
    with open(custom_devices_file, "w+", encoding="utf-8") as file:
        json.dump(custom_devices, file, indent=4)

    return


def add_flutter_custom_device_ex(custom_device):
    """ Add a single Flutter custom device from JSON string """

    if not validate_custom_device_config(custom_device):
        print("Invalid Custom Device configuration")
        sys.exit(1)

    device_config = fixup_custom_device(custom_device)
    # print("Adding custom-device: %s" % device_config)

    custom_devices_file = get_flutter_custom_config_path()

    new_device_list = []
    if os.path.exists(custom_devices_file):

        f = open(custom_devices_file, "r", encoding="utf-8")
        try:
            obj = json.load(f)
        except json.decoder.JSONDecodeError:
            print_banner("Invalid JSON in %s" %
                         custom_devices_file)  # in case JSON is invalid
            exit(1)
        f.close()

        id_ = device_config['id']

        if 'custom-devices' in obj:
            devices = obj['custom-devices']
            for device in devices:
                if 'id' in device and id_ != device['id']:
                    new_device_list.append(device)

    new_device_list.append(device_config)
    # patched_device_list = patch_custom_device_strings_ex(new_device_list)

    custom_devices = {'custom-devices': new_device_list}

    print("custom_devices_file: %s" % custom_devices_file)
    with open(custom_devices_file, "w+", encoding="utf-8") as file:
        json.dump(custom_devices, file, indent=4)

    return


def handle_custom_devices(platform_):
    """ Updates the custom_devices.json with platform config """

    if "custom-device" not in platform_:
        print_banner("No custom-device key in platform config")
        return

    custom_devices = get_flutter_custom_devices()

    overwrite_existing = platform_.get('overwrite-existing')

    # check if id already exists, remove if overwrite enabled, otherwise skip
    if custom_devices:
        for custom_device in custom_devices:
            if 'id' in custom_device:
                id_ = custom_device['id']
                if overwrite_existing and (id_ == platform_['id']):
                    # print("attempting to remove custom-device: %s" % id_)
                    remove_flutter_custom_devices_id(id_)

    add_flutter_custom_device_ex(
        platform_['custom-device'])


def configure_flutter_sdk():
    """ Configure Flutter SDK """
    # Mux flutter and dart commands based on platform
    if sys.platform.startswith('win'):
        flutter_cmd = 'flutter.bat'
        dart_cmd = 'dart.bat'
    else:
        flutter_cmd = 'flutter'
        dart_cmd = 'dart'

    cmd = [flutter_cmd, 'config', '--no-analytics', '--no-enable-web', '--no-enable-android', '--no-enable-ios', '--no-enable-fuchsia', '--enable-custom-devices']

    host = get_host_type()
    if host == 'darwin':
        cmd.append('--enable-macos-desktop')
        cmd.append('--no-enable-linux-desktop')
        cmd.append('--no-enable-windows-desktop')
    elif host == 'linux':
        cmd.append('--enable-linux-desktop')
        cmd.append('--no-enable-macos-desktop')
        cmd.append('--no-enable-windows-desktop')
    elif host == 'windows':
        cmd.append('--enable-windows-desktop')
        cmd.append('--no-enable-linux-desktop')
        cmd.append('--no-enable-macos-desktop')

    subprocess.check_call(cmd)

    cmd = [flutter_cmd, 'config', '--list']
    subprocess.check_call(cmd)

    subprocess.check_call(cmd)
    cmd = [flutter_cmd, 'doctor', '-v']
    subprocess.check_call(cmd)


def force_tool_rebuild(flutter_sdk_folder):
    tool_script = os.path.join(
        flutter_sdk_folder, 'bin', 'cache', 'flutter_tools.snapshot')

    if os.path.exists(tool_script):
        print_banner("Cleaning Flutter Tool")
        os.remove(tool_script)


def patch_flutter_sdk(flutter_sdk_folder):
    host = get_host_type()

    if host == "linux":
        print_banner("Patching Flutter SDK")

        cmd = ["bash", "-c", "sed -i -e \"/const Feature flutterCustomDevicesFeature/a const"
                             " Feature flutterCustomDevicesFeature = Feature\\(\\n  name: "
                             "\\\'Early support for custom device types\\\',\\n  configSetting:"
                             " \\\'enable-custom-devices\\\',\\n  environmentOverride: "
                             "\\\'FLUTTER_CUSTOM_DEVICES\\\',\\n  master: FeatureChannelSetting"
                             "(\\n    available: true,\\n  \\),\\n  beta: FeatureChannelSetting"
                             "\\(\\n    available: true,\\n  \\),\\n  stable: "
                             "FeatureChannelSetting(\\n    available: true,\\n  \\)\\n);\" -e "
                             "\"/const Feature flutterCustomDevicesFeature/,/);/d\" packages/"
                             "flutter_tools/lib/src/features.dart"]
        subprocess.check_call(cmd, cwd=flutter_sdk_folder)


# Check if the flutter SDK path exists. Pull if exists. Create dir and clone sdk if not.
def get_flutter_sdk(version):
    """ Get Flutter SDK clone """

    workspace = os.environ.get('FLUTTER_WORKSPACE')

    flutter_sdk_path = os.path.join(workspace, 'flutter')

    #
    # GIT repo
    #
    if is_repo(flutter_sdk_path):

        print('Checking out %s' % version)
        cmd = ["git", "fetch", "--all"]
        subprocess.check_call(cmd, cwd=flutter_sdk_path)
        cmd = ["git", "reset", "--hard"]
        subprocess.check_call(cmd, cwd=flutter_sdk_path)
        cmd = ["git", "checkout", version]
        subprocess.check_call(cmd, cwd=flutter_sdk_path)

    else:

        flutter_repo = 'https://github.com/flutter/flutter.git'

        cmd = ['git', 'clone', flutter_repo, flutter_sdk_path]
        subprocess.check_call(cmd)

        print('Checking out %s' % version)
        cmd = ["git", "checkout", version]
        subprocess.check_call(cmd, cwd=flutter_sdk_path)

    print_banner("FLUTTER_SDK: %s" % flutter_sdk_path)

    return flutter_sdk_path


def get_flutter_engine_version(flutter_sdk_path):
    """ Get Engine Commit from Flutter SDK """

    # check if mono repo
    engine_folder = os.path.join(flutter_sdk_path, 'engine')
    os.environ['MONO_REPO'] = "0"
    if os.path.isdir(engine_folder):
        os.environ['MONO_REPO'] = "1"

    engine_version_file = os.path.join(
        flutter_sdk_path, 'bin/internal/engine.version')

    if not os.path.exists(engine_version_file):
        print("Missing Flutter SDK")
        sys.exit(1)

    with open(engine_version_file, encoding="utf-8") as f:
        engine_version = f.read()
        print(f"Engine Version: {engine_version.strip()}")

    return engine_version.strip()


def get_process_stdout(cmd):
    process = subprocess.Popen(
        shlex_quote(cmd), shell=True, stdout=subprocess.PIPE, universal_newlines=True)
    ret = ""
    for line in process.stdout:
        ret += str(line)
    process.wait()
    return ret


def get_freedesktop_os_release() -> dict:
    """ Read /etc/os-release into dictionary """
    if not os.path.exists("/etc/os-release"):
        return {}

    with open("/etc/os-release", encoding="utf-8") as f:
        d = {}
        for line in f:
            line = line.strip()
            if "=" in line:  # Only process lines containing "="
                k, v = line.rstrip().split("=", 1)  # Split on first "=" only
                d[k] = v.strip('"')
        return d


def get_freedesktop_os_release_name() -> str:
    """Returns OS Release NAME value"""
    return get_freedesktop_os_release().get('NAME','').lower().rstrip()


def get_freedesktop_os_release_id() -> str:
    """Returns OS Release ID value"""
    return get_freedesktop_os_release().get('ID','').lower().rstrip()


def get_freedesktop_os_release_version_id() -> str:
    """Returns OS Release VERSION_ID value"""
    return get_freedesktop_os_release().get('VERSION_ID','').rstrip()


def break_version(version):
    import re
    match = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?$', version)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2)) if match.group(2) else 0
        patch = int(match.group(3)) if match.group(3) else 0
        return major, minor, patch
    else:
        raise ValueError("Invalid version format")


def get_darwin_version() -> str:
    """Returns Darwin version value"""
    return platform.mac_ver()[0]


def get_darwin_major_version() -> str:
    """Returns Darwin version value"""
    version = get_darwin_version()
    major, _, _ = break_version(version)
    print_banner(f'Darwin {major}')
    return str(major)


def get_windows_major_version() -> str:
    """Returns Windows major version value as string"""
    version = platform.version()
    # Example: '10.0.22621'
    parts = version.split('.')
    if parts:
        return parts[0]
    return ""


def get_host_type() -> str:
    """Returns host system"""
    return system().lower().rstrip()


def get_flutter_engine_commit():
    workspace = os.environ.get('FLUTTER_WORKSPACE')
    if not workspace:
        print("FLUTTER_WORKSPACE not set")
        sys.exit(1)

    flutter_sdk_path = os.path.join(workspace, 'flutter')

    engine_version = get_flutter_engine_version(flutter_sdk_path)
    os.environ['FLUTTER_ENGINE_VERSION'] = engine_version
    return engine_version


def set_gen_snapshot(runtime, arch):
    # set environment variables
    commit = get_flutter_engine_commit()
    arch = get_flutter_arch()

    engine_sdk = f'engine-sdk-{runtime}-{arch}'

    linux_runtime = f'linux_{runtime}_{arch}'

    platform_path = get_platform_working_dir('flutter-engine')

    engine_sdk_root = os.path.join(platform_path, commit, engine_sdk, 'flutter', 'engine', 'src', 'out', linux_runtime, 'engine-sdk')

    gen_snapshot = os.path.join(engine_sdk_root, 'bin', 'gen_snapshot')
    
    if not os.path.exists(gen_snapshot):
        get_flutter_engine_artifacts(True, runtime, arch)

    if not os.path.exists(gen_snapshot):
        print('engine-sdk error')
        sys.exit(1)

    os.environ['GEN_SNAPSHOT'] = gen_snapshot


def get_engine_sdk_url(runtime, arch):
    commit = get_flutter_engine_commit()
    if arch == 'x64':
        arch = 'x86_64'
    elif arch == 'arm':
        arch = 'armv7hf'
    url = f'https://github.com/meta-flutter/flutter-engine/releases/download/linux-engine-sdk-{runtime}-{arch}-{commit}/linux-engine-sdk-{runtime}-{arch}-{commit}.tar.gz'
    return url, commit


def get_flutter_engine_artifacts(clean_workspace, runtime, arch):
    """Downloads Flutter Engine Runtime"""

    base_url, engine_version = get_engine_sdk_url(runtime, arch)

    _, filename = os.path.split(base_url)

    cwd = get_platform_working_dir('flutter-engine')

    cwd_engine = os.path.join(cwd, engine_version)

    archive_file = os.path.join(cwd_engine, filename)
    sha256_file = os.path.join(cwd_engine, filename + '.sha256')

    bundle_folder = os.path.join(cwd, f'bundle-{runtime}-{arch}')
    os.environ['BUNDLE_FOLDER'] = bundle_folder

    if not compare_sha256(archive_file, sha256_file):
        print_banner("Downloading Engine artifact")
        os.makedirs(cwd_engine, exist_ok=True)
        if not download_https_file(cwd_engine, base_url, filename,
                                   None, None, None, None, None, True):
            print_banner("Engine artifact not available")
            return
    else:
        print_banner("Skipping Engine artifact download")

    restore_folder = os.path.join(cwd_engine, f'engine-sdk-{runtime}-{arch}')
    os.makedirs(restore_folder, exist_ok=True)
    subprocess.check_call(['tar', '-xzf', archive_file, '-C', restore_folder])

    if clean_workspace:
        if os.path.exists(bundle_folder):
            shutil.rmtree(bundle_folder)

    # stage bundle layout
    data_folder = os.path.join(bundle_folder, 'data')
    os.makedirs(data_folder, exist_ok=True)

    lib_folder = os.path.join(bundle_folder, 'lib')
    os.makedirs(lib_folder, exist_ok=True)

    # mono repo builds include two additional folders in path
    if (os.environ['MONO_REPO'] == "1"):
        icudtl_src = os.path.join(restore_folder, 'flutter', 'engine', 'src', 'out', f'linux_{runtime}_{arch}', 'engine-sdk', 'data',
                                  'icudtl.dat')

        libflutter_engine_src = os.path.join(restore_folder, 'flutter', 'engine', 'src', 'out', f'linux_{runtime}_{arch}', 'engine-sdk',
                                             'lib',
                                             'libflutter_engine.so')
    else:
        icudtl_src = os.path.join(restore_folder, 'src', 'out', f'linux_{runtime}_{arch}', 'engine-sdk', 'data',
                                  'icudtl.dat')

        libflutter_engine_src = os.path.join(restore_folder, 'src', 'out', f'linux_{runtime}_{arch}', 'engine-sdk',
                                             'lib',
                                             'libflutter_engine.so')

    shutil.copy(icudtl_src, data_folder)
    shutil.copy(libflutter_engine_src, lib_folder)


def get_flutter_engine_runtime(clean_workspace, arch):
    get_flutter_engine_artifacts(clean_workspace, 'release', arch)
    get_flutter_engine_artifacts(clean_workspace, 'profile', arch)
    get_flutter_engine_artifacts(clean_workspace, 'debug', arch)


def handle_conditionals(conditionals, cwd):
    if not conditionals:
        return

    print(conditionals)
    for condition in conditionals:
        path = os.path.normpath(os.path.expandvars(condition['path']))
        print(path)

        if not os.path.exists(path):
            print("** Conditionals **")
            for cmd_str in condition['cmds']:
                cmd_str = os.path.normpath(os.path.expandvars(cmd_str))
                cmd_arr = shlex.split(cmd_str, posix=not sys.platform.startswith('win'))
                print(cmd_arr)
                subprocess.call(cmd_arr, cwd=cwd)


def handle_pre_requisites(obj, cwd):
    if not obj:
        return

    host_machine_arch = get_host_machine_arch()

    if host_machine_arch in obj:
        host_specific_pre_requisites = obj[host_machine_arch]

        host_type = get_host_type()

        host_os_version_id = ''
        host_os_release_id = ''
        if host_type == "linux":
            host_os_release_id = get_freedesktop_os_release_id()
            host_os_version_id = get_freedesktop_os_release_version_id()
        elif host_type == "darwin":
            host_os_release_id = "darwin"
            host_os_version_id = get_darwin_major_version()
        elif host_type == "windows":
            host_os_release_id = "windows"
            host_os_version_id = get_windows_major_version()

        if host_specific_pre_requisites.get(host_os_release_id):
            distro = host_specific_pre_requisites[host_os_release_id]
            handle_conditionals(distro.get('conditionals'), cwd)
            handle_commands_obj(distro, cwd)

            if distro.get(host_os_version_id):
                os_version = distro[host_os_version_id]
                handle_commands_obj(os_version, cwd)
        else:
            print(f'handle_pre_requisites: Not supported: [{host_os_release_id}, {host_os_version_id}]')


def get_filename_from_url(url):
    import os
    from urllib.parse import urlparse

    a = urlparse(url)
    return os.path.basename(a.path)


def check_netrc_for_str(pattern):
    if not pattern:
        return False

    from pathlib import Path

    p = Path('~').expanduser()
    netrc = p.joinpath(".netrc")

    if not os.path.exists(netrc):
        print_banner("~/.netrc does not exist")
        return False

    file = open(netrc, "r", encoding="utf-8")
    for line in file:
        if pattern in line:
            file.close()
            return True

    file.close()
    print_banner("Missing %s from ~/.netrc" % pattern)
    return False


def handle_netrc_obj(obj):
    if not obj:
        return False

    if not check_netrc_for_str(obj.get('machine')):
        print("Fix ~/.netrc to continue")
        sys.exit(1)
    else:
        print('~/.netrc is good')
        return True


def handle_http_obj(obj, host_machine_arch, cwd, cookie_file, netrc):
    if not obj:
        return

    if 'artifacts' not in obj:
        return

    artifacts = obj['artifacts']

    if 'cookie_file' in obj:
        cookie_file = obj['cookie_file']

    if host_machine_arch in artifacts:
        host_specific_artifacts = artifacts[host_machine_arch]

        url = None
        if 'url' in obj:
            url = obj['url']

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = []
            for artifact in host_specific_artifacts:
                local_url = artifact.get('url')
                if local_url is None:
                    local_url = url

                base_url = local_url + artifact['endpoint']
                base_url = os.path.expandvars(base_url)
                filename = os.path.expandvars(artifact.get('filename', get_filename_from_url(base_url)))

                print(f'url: {base_url}')
                print(f'filename: {filename}')

                futures.append(executor.submit(download_https_file, cwd, base_url, filename, cookie_file,
                                               netrc, artifact.get('md5'), artifact.get('sha1'),
                                               artifact.get('sha256'), True, None))
                validate_sudo_user()

            for future in concurrent.futures.as_completed(futures):
                future.result()
                validate_sudo_user()

            for artifact in host_specific_artifacts:
                handle_post_cmds(artifact.get('post_cmds'))


def handle_post_cmds(post_cmds):
    if not post_cmds:
        return

    for post_cmd in post_cmds:
        cwd = post_cmd.get('cwd')
        if not cwd:
            print_banner("Warning: Missing `cwd` key in post_cmds, using current working directory")
            cwd = os.getcwd()

        handle_commands_obj(post_cmd, cwd)


def handle_commands_obj(obj, cwd):
    if not obj:
        return
    
    print_banner(f'Handling commands object: {obj}')

    host_type = get_host_type()
    if host_type == 'linux':
        host_type = get_freedesktop_os_release_id()

    print(f'host_type: {host_type}')

    # sandbox variables to commands
    if host_type in obj:
        cmds = obj[host_type]
        if 'env' in cmds:
            handle_env(cmds.get('env'), None)

    local_env = os.environ.copy()
    if 'env' in obj:
        handle_env(obj.get('env'), local_env)

    print(f'local_env: {local_env}')

    orig_env = os.environ.copy()
    os.environ.update(local_env)

    if 'cwd' in obj:
        cwd = obj.get('cwd')

    if cwd:
        print(f'cwd raw: {cwd}')
        cwd = os.path.expanduser(cwd)
        print(f'cwd expanduser: {cwd}')
        cwd = string.Template(cwd).safe_substitute(local_env)
        print(f'cwd safe_substitute: {cwd}')
        cwd = os.path.normpath(cwd)
        print(f'cwd normpath: {cwd}')
        os.makedirs(cwd, exist_ok=True)

    shell_ = False
    if 'shell' in obj:
        shell_ = obj.get('shell')

    posix = not host_type == 'windows'

    cmds = obj.get('cmds', [])
    for cmd in cmds:
        print(f'cmd raw: {cmd}')
        cmd = os.path.expanduser(cmd)
        print(f'cmd expanduser: {cmd}')
        cmd = string.Template(cmd).safe_substitute(local_env)
        print(f'cmd safe_substitute: {cmd}')

        if host_type == 'windows':
            cmd = os.path.normpath(cmd)
            print(f'cmd normpath: {cmd}')

            if cmd.startswith('python') or cmd.startswith('cmake') or cmd.startswith('git') and host_type == 'windows':
                cmd = cmd.replace('\\', '/')
                posix = True
                print(f'cmd: {cmd}')


        if shell_:
            # If shell is True, we need to join the command as a single string
            print(f'cmd: {cmd}')
            subprocess.check_call(cmd, cwd=cwd, env=local_env, shell=shell_, stderr=subprocess.STDOUT, universal_newlines=True)
        else:
            # If shell is False, we pass the command as a list
            cmd_arr = shlex.split(cmd, posix=posix)
            print(f'cmd: {cmd_arr}')
            subprocess.check_call(cmd_arr, cwd=cwd, env=local_env, shell=shell_, stderr=subprocess.STDOUT, universal_newlines=True)

    os.environ.clear()
    os.environ.update(orig_env)


def handle_docker_registry(obj):
    if 'registry' in obj:
        registry = obj['registry']
        cmd = ["docker", "login", registry]
        subprocess.call(cmd)


def docker_compose_start(docker_compose_yml_dir):
    if not docker_compose_yml_dir:
        return

    subprocess.check_call(["docker-compose", "up", "-d"],
                          cwd=docker_compose_yml_dir)


def docker_compose_stop(docker_compose_yml_dir):
    if not docker_compose_yml_dir:
        return

    subprocess.check_call(["docker-compose", "stop"],
                          cwd=docker_compose_yml_dir)


def handle_docker_obj(obj, _, cwd):
    if not obj:
        return

    from pathlib import Path

    flutter_workspace = os.environ['FLUTTER_WORKSPACE']

    # handle_docker_registry(obj.get('registry'))

    docker_compose_yml_dir = obj.get('docker-compose-yml-dir')
    if docker_compose_yml_dir:
        docker_compose_yml_abs = os.path.join(flutter_workspace, docker_compose_yml_dir)
        if Path(docker_compose_yml_abs).exists():
            docker_compose_stop(docker_compose_yml_abs)

    handle_post_cmds(obj.get('post_cmds'))
    handle_conditionals(obj.get('conditionals'), cwd)


env_qemu = '''
echo \"********************************************\"
echo \"* Type 'run-%s' to start"
echo \"********************************************\"
run-%s() {
    if [[ $( (echo >/dev/tcp/localhost/%s) &>/dev/null; echo $?) -eq 0 ]];
    then
        echo 'port %s is already in use'
    else
        %s
    fi
}
'''

env_qemu_applescript = '''
#!/usr/bin/osascript

tell application "Finder"
        set flutter_workspace to system attribute "FLUTTER_WORKSPACE"
    set p_path to POSIX path of flutter_workspace
    tell application "Terminal"
        activate
        set a to do script "cd " & quoted form of p_path & " && %s %s"
    end tell
end tell
'''

def handle_qemu_obj(qemu: dict, cwd: os.path, platform_id: str, flutter_runtime: str):
    if qemu is None:
        return

    host_machine_arch = get_host_machine_arch()

    qemu_arch_config = qemu.get(host_machine_arch)
    if not qemu_arch_config:
        print_banner(f"QEMU configuration not specified for architecture: {host_machine_arch}")
        return
    if not qemu.get('cmd'):
        print_banner("QEMU command not specified")
        return

    if qemu.get('extra'):
        extra = ''
        host_type = get_host_type()
        if 'linux' == host_type:
            host_type = get_freedesktop_os_release_id()
            if is_linux_host_kvm_capable():
                extra = '-enable-kvm '
        if host_type not in qemu['extra']:
            print("Extra parameters not specified for this host type")
            sys.exit(1)
        extra = extra + qemu['extra'][host_type]
        os.environ['QEMU_EXTRA'] = os.path.expandvars(extra)

    if host_machine_arch == 'arm64':
        os.environ['FORMAL_MACHINE_ARCH'] = 'aarch64'
    elif host_machine_arch == 'x86_64':
        os.environ['FORMAL_MACHINE_ARCH'] = 'x86_64'

    os.environ['RANDOM_MAC'] = get_random_mac()
    os.environ['FLUTTER_RUNTIME'] = flutter_runtime

    cmd = qemu['cmd']
    cmd = os.path.expandvars(cmd)

    if 'kernel' in qemu[host_machine_arch]:
        kernel = qemu[host_machine_arch]['kernel']
        kernel = os.path.expandvars(kernel)
        os.environ['QEMU_KERNEL'] = os.path.join(cwd, kernel)

    image = qemu[host_machine_arch]['image']
    image = os.path.expandvars(image)

    artifacts_dir = os.environ.get('ARTIFACTS_DIR')
    if not artifacts_dir:
        os.environ['QEMU_IMAGE'] = os.path.join(cwd, image)
    else:
        os.environ['QEMU_IMAGE'] = os.path.join(artifacts_dir, image)

    args = qemu[host_machine_arch]['args']
    args = os.path.expandvars(args)

    flutter_workspace = os.environ['FLUTTER_WORKSPACE']

    terminal_cmd = ''
    host_type = get_host_type()
    if host_type == "linux":
        terminal_cmd = f'gnome-terminal -- bash -c "{cmd} {args}"'
        # terminal_cmd = cmd + " " + args
    elif host_type == "darwin":
        apple_script_filename = 'run-' + platform_id + '.scpt'
        terminal_cmd = f'osascript "$FLUTTER_WORKSPACE/{apple_script_filename}"'
        apple_script_file = os.path.join(
            flutter_workspace, apple_script_filename)
        with open(apple_script_file, 'w+', encoding="utf-8") as file:
            file.write(env_qemu_applescript % (cmd, args))

    # Use SSH port from qemu config or environment, with a default value of 2222
    container_ssh_port = qemu.get('ssh_port') or os.environ.get('CONTAINER_SSH_PORT', "2222")
    # Store the SSH port in environment for other components to use
    os.environ['CONTAINER_SSH_PORT'] = container_ssh_port

    env_script = os.path.join(flutter_workspace, 'setup_env.sh')
    with open(env_script, 'a+', encoding="utf-8") as f:
        f.write(env_qemu % (
            platform_id,
            platform_id,
            container_ssh_port,
            container_ssh_port,
            terminal_cmd))


def handle_github_obj(obj, cwd, token):
    if not obj:
        return

    if 'owner' in obj and 'repo' in obj and 'workflow' in obj and 'artifact_names' in obj:
        print_banner("Downloading GitHub artifact")

        owner = obj['owner']
        repo = obj['repo']
        workflow = obj['workflow']
        artifact_names = obj['artifact_names']
        post_process = obj.get('post_process')

        workflow_runs = get_github_workflow_runs(token, owner, repo, workflow)
        run_id = None
        for run in workflow_runs:
            if run['conclusion'] == "success":
                run_id = run['id']
                break

        artifacts = get_github_workflow_artifacts(token, owner, repo, run_id)

        for artifact in artifacts:

            name = artifact.get('name')
            print(name)

            for artifact_name in artifact_names:

                if artifact_name == name:
                    url = artifact.get('archive_download_url')

                    print("Downloading %s run_id: %s via %s" %
                          (workflow, run_id, url))

                    filename = "%s.zip" % name
                    downloaded_file = get_github_artifact(token, url, filename)
                    if downloaded_file is None or downloaded_file == '':
                        print_banner("Failed to download %s" % filename)
                        continue

                    print("Downloaded: %s" % downloaded_file)

                    with zipfile.ZipFile(downloaded_file, "r") as zip_ref:
                        zip_ref.extractall(str(cwd))

                    shutil.remove(downloaded_file)
                    subprocess.check_output(cmd)
                    continue

        if post_process:
            for cmd in post_process:
                expanded_cmd = os.path.normpath(os.path.expandvars(cmd))
                cmd_arr = shlex.split(expanded_cmd, posix=not sys.platform.startswith('win'))
                subprocess.call(cmd_arr, cwd=cwd, env=os.environ)


def handle_artifacts_obj(obj, host_machine_arch, cwd, git_token, cookie_file):
    if not obj:
        return

    artifacts = os.path.join(cwd, 'artifacts')
    os.makedirs(artifacts, exist_ok=True)
    os.environ['ARTIFACTS_DIR'] = artifacts
    cwd = artifacts

    if not cookie_file:
        cookie_file = obj.get('cookie_file')

    netrc = handle_netrc_obj(obj.get('netrc'))
    handle_http_obj(obj.get('http'), host_machine_arch,
                    cwd, cookie_file, netrc)
    handle_github_obj(obj.get('github'), cwd, git_token)


def handle_dotenv(dotenv_files):
    if not dotenv_files:
        return

    from dotenv import load_dotenv
    from pathlib import Path

    flutter_workspace = os.environ['FLUTTER_WORKSPACE']

    for dotenv_file in dotenv_files:
        dotenv_path = Path(os.path.join(flutter_workspace, dotenv_file))
        if dotenv_path.exists:
            load_dotenv(dotenv_path=dotenv_path, verbose=True, override=True)
            print(f'Loaded: {dotenv_path}')


def handle_env(env_variables, local_env, build_type=None):
    if not env_variables:
        return

    for k, v in env_variables.items():
        if local_env:
            if 'PATH_PREPEND' in k:
                local_env['PATH'] = os.path.normpath(os.path.expandvars(v)) + os.pathsep + local_env['PATH']
                continue
            if 'PATH_APPEND' in k:
                local_env['PATH'] = local_env['PATH'] + os.pathsep + os.path.normpath(os.path.expandvars(v))
                continue

            handle_build_type(local_env, build_type)

            local_env[k] = os.path.normpath(os.path.expandvars(v))
        else:
            if 'PATH_PREPEND' in k:
                os.environ['PATH'] = os.path.normpath(os.path.expandvars(v)) + os.pathsep + os.environ['PATH']
                continue
            if 'PATH_APPEND' in k:
                os.environ['PATH'] = os.environ['PATH'] + os.pathsep + os.path.normpath(os.path.expandvars(v))
                continue

            handle_build_type(os.environ, build_type)

        os.environ[k] = os.path.normpath(os.path.expandvars(v)) 
        # print(f'global: {k} = {os.environ[k]}')


def handle_build_type(env, build_type=None):
    # set default from globals
    if build_type is None:
        build_type = globals_.get('build_type')


    env['_BUILD_TYPE'] = build_type
    env['CMAKE_BUILD_TYPE'] = build_types_cmake[build_type]
    env['MESON_BUILD_TYPE'] = build_types_meson[build_type]
    

def get_platform_working_dir(platform_id):
    from pathlib import Path
    workspace = Path(os.environ.get('FLUTTER_WORKSPACE'))
    cwd = workspace.joinpath('.config', 'flutter_workspace', platform_id)
    os.environ["PLATFORM_ID_DIR_RELATIVE"] = '.' + platform_id
    os.environ["PLATFORM_ID_DIR"] = str(cwd)
    print(f'Working Directory: {cwd}')
    os.makedirs(cwd, exist_ok=True)
    return cwd


def create_platform_config_file(obj, cwd):
    import toml
    from pathlib import Path
    if obj is None:
        return

    toml_config = toml.dumps(obj)

    cwd = Path(cwd)
    default_config_filepath = cwd.joinpath('config.toml')
    if not default_config_filepath.exists():
        os.makedirs(default_config_filepath.parent, exist_ok=True)
    with open(default_config_filepath, 'w+', encoding="utf-8") as f:
        f.write(toml_config)


def create_gclient_config_file(obj):
    if obj is None:
        return

    if 'path' not in obj:
        print_banner('Missing path key in gclient_config')
        return

    gclient_path = obj['path']
    gclient_path = os.path.expandvars(gclient_path)
    os.makedirs(gclient_path, exist_ok=True)

    del obj['path']
    gclient_config = json.dumps(obj)
    gclient_config = 'solutions = [' + gclient_config
    gclient_config = os.path.expandvars(gclient_config)
    gclient_config = gclient_config.replace('true', 'True')
    gclient_config = gclient_config.replace('false', 'False')
    gclient_config = gclient_config + ']'

    gclient_config_file = os.path.join(gclient_path, '.gclient')
    with open(gclient_config_file, 'w+', encoding="utf-8") as f:
        f.write(gclient_config)


def is_host_type_supported(host_types):
    """Return true if host type is contained in host_types variable, false otherwise"""
    host_type = get_host_type()

    if host_type == 'linux':
        host_type = get_freedesktop_os_release_id()

    if host_type not in host_types:
        return False
    return True


def handle_plugin_variables(enable_plugin, disable_plugin):
    """ Set plugin environmental variables """
    plugins = []

    if enable_plugin:
        for it in enable_plugin:
            plugins.append(f' -DBUILD_PLUGIN_{it.upper()}=ON')

    if disable_plugin:
        for it in disable_plugin:
            plugins.append(f' -DBUILD_PLUGIN_{it.upper()}=OFF')

    plugins = "".join(plugins)

    os.environ['CMD_LINE_CMAKE_PLUGIN_ARGS'] = plugins

    print_banner('CMD_LINE_CMAKE_PLUGIN_ARGS=' + os.environ.get('CMD_LINE_CMAKE_PLUGIN_ARGS', 'Not Set'))


def setup_platform(platform_, git_token, cookie_file, plex, enable, disable, enable_plugin, disable_plugin, app_folder):
    """ Sets up platform """

    if 'type' in platform_:
        if platform_['type'] == 'toolchain':
            print("WARNING! Calling setup_platform on a config of type 'toolchain'")
            return

    # setup environmental variable to use in later occuring CMake configs
    if 'load' in platform_ and 'id' in platform_:
        platform_id = platform_['id']
        id_conv = platform_id.replace('-', '_')
        id_upper = id_conv.upper()

        if platform_id in disable or platform_id in plex:
            value = "OFF"
        elif platform_id in enable or platform_['load']:
            value = "ON"
        else:
            value = "OFF"

        # skip if distro not supported
        if not is_host_type_supported(platform_['supported_host_types']):
            value = "OFF"
            print(f'WARNING: {platform_id} not supported on this host type: {get_host_type()}')

        # skip if architecture not supported
        host_machine_arch = get_host_machine_arch()
        if host_machine_arch not in platform_['supported_archs']:
            value = "OFF"
            print(f'WARNING: {platform_id} not supported on this machine architecture: {host_machine_arch}')

        key = f'FLUTTER_WORKSPACE_{id_upper}_LOAD'
        print(f'{key}={value}')
        os.environ[key] = value

        if value == "OFF":
            print_banner("Skipping - %s" % platform_['id'])
            return -1

    get_platform_src(platform_.get('src', None), app_folder)

    # if platform_['type'] == 'docker':
    runtime = platform_['runtime']

    # skip if architecture not supported
    host_machine_arch = get_host_machine_arch()
    if host_machine_arch not in platform_['supported_archs']:
        print_banner("\"%s\" not supported on this machine" % platform_['id'])
        return -1

    # skip if distro not supported
    if not is_host_type_supported(platform_['supported_host_types']):
        print_banner("\"%s\" not supported on this host type" %
                     platform_['id'])
        return -1

    print_banner("Setting up Platform %s - %s" %
                 (platform_['id'], host_machine_arch))

    cwd = get_platform_working_dir(platform_['id'])

    validate_sudo_user()

    handle_dotenv(platform_.get('dotenv'))
    handle_env(platform_.get('env'), None, build_types.get(platform_['id'], None))

    print(f"Build type: {os.environ.get('_BUILD_TYPE', '<unset>')}")

    create_platform_config_file(runtime.get('config'), cwd)
    create_gclient_config_file(runtime.get('gclient_config'))
    validate_sudo_user()
    handle_artifacts_obj(runtime.get('artifacts'),
                         host_machine_arch, cwd, git_token, cookie_file)
    validate_sudo_user()
    handle_plugin_variables(enable_plugin, disable_plugin)
    handle_pre_requisites(runtime.get('pre-requisites'), cwd)
    validate_sudo_user()
    handle_docker_obj(runtime.get('docker'), host_machine_arch, cwd)
    validate_sudo_user()
    handle_conditionals(runtime.get('conditionals'), cwd)
    validate_sudo_user()
    handle_qemu_obj(runtime.get('qemu'), cwd, platform_[
        'id'], 'debug')
    validate_sudo_user()
    handle_post_cmds(runtime.get('post_cmds'))

    handle_custom_devices(platform_)

    return 0


def get_first_file_in_path(path, file_to_find):
    for root, _, files in os.walk(path):
        for file in files:
            if file == file_to_find:
                file_path = os.path.join(root, file)
                if os.access(file_path, os.X_OK):
                    if 'android' in file_path:
                        continue
                    return file_path

    return None


def get_llvm_config(llvm_config, option):
    if not os.access(llvm_config, os.X_OK):
        print(f"Error: {llvm_config} is not executable or not accessible.")
        return None

    try:
        result = subprocess.run([llvm_config, f'--{option}'], capture_output=True, text=True, check=True)
        prefix_path = result.stdout.strip()
        return prefix_path
    except subprocess.CalledProcessError as e:
        print(f"Error occurred: {e}")
        return None


def get_hardware_threads():
    if os.getenv('HARDWARE_THREADS'):
        return int(os.getenv('HARDWARE_THREADS'))

    import multiprocessing
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return multiprocessing.cpu_count()


def setup_llvm_vars(llvm_config):
    print_banner(f"Setting up LLVM variables using {llvm_config}")

    llvm_bindir = get_llvm_config(llvm_config, 'bindir')
    llvm_libdir = get_llvm_config(llvm_config, 'libdir')

    os.environ['LLVM_BINDIR'] = llvm_bindir
    os.environ['LLVM_LIBDIR'] = llvm_libdir
    os.environ['LLVM_CONFIG'] = llvm_bindir + '/llvm-config'

    print(f"LLVM_BINDIR: {os.environ['LLVM_BINDIR']}")
    print(f"LLVM_CONFIG: {os.environ['LLVM_CONFIG']}")


def setup_toolchain(platform_, git_token, cookie_file, plex, enable, disable, enable_plugin, disable_plugin,
                    app_folder):
    if not 'toolchain' in platform_:
        print_banner("Toolchain key not specified")
        return

    hw_threads = get_hardware_threads()
    if not os.getenv('GITHUB_ACTIONS'):
        if hw_threads > 1:
            hw_threads = hw_threads - 1
    os.environ['HARDWARE_THREADS'] = str(hw_threads)

    # Get LLVM version
    if platform_['toolchain'] == 'llvm':
        prefer_llvm = os.environ.get('PREFER_LLVM', None)
        if not prefer_llvm:
            # If not set by ENV variable, get default from platform config
            if 'DEFAULT_VERSION' in platform_['env']:
                prefer_llvm = platform_['env']['DEFAULT_VERSION']
                os.environ['PREFER_LLVM'] = prefer_llvm
                print(f'PREFER_LLVM: {prefer_llvm}')

        # Failsafe
        if not prefer_llvm:
            print("PREFER_LLVM is not set and no prefer_llvm key present in toolchain config")
            sys.exit(1)

    platform_['type'] = 'dependency'
    do_continue = setup_platform(platform_, git_token, cookie_file, plex, enable, disable, enable_plugin, disable_plugin, app_folder)
    if do_continue != 0:
        return
    platform_['type'] = 'toolchain'

    host_type = get_host_type()
    if host_type == 'linux':
        host_type = get_freedesktop_os_release_id()


    if platform_['toolchain'] == 'llvm':
        llvm_base_path = '/usr'

        if host_type == 'darwin':
            llvm_base_path = get_mac_brew_prefix('llvm' + '@' + prefer_llvm)
        elif host_type == 'ubuntu':
            llvm_base_path = '/usr/lib/llvm-' + prefer_llvm + '/bin'
        elif host_type == 'fedora':
            llvm_base_path = '/usr/lib64/llvm' + prefer_llvm + '/bin'

        print(f'Looking for llvm-config in {llvm_base_path}')
        llvm_config = get_first_file_in_path(llvm_base_path, 'llvm-config')
        if llvm_config:
            setup_llvm_vars(llvm_config)
        else:
            llvm_base_path = '/usr'
            llvm_config = get_first_file_in_path(llvm_base_path, 'llvm-config')
            if llvm_config:
                setup_llvm_vars(llvm_config)
            else:
                print_banner(f'Failed to find llvm-config({prefer_llvm}) in {llvm_base_path}.')
                exit()
                return

    elif platform_['toolchain'] == 'common':
        pass
    else:
        print_banner("Toolchain not supported")

    # get host type and check if present in platform_['append_to_runtime_env'], if not attempt to use common
    if host_type in platform_['append_to_runtime_env']:
        append_to_runtime_env = platform_['append_to_runtime_env'][host_type]
    elif 'common' in platform_['append_to_runtime_env']:
        append_to_runtime_env = platform_['append_to_runtime_env']['common']
    else:
        append_to_runtime_env = []

    # append lines to runtime env script (for both llvm and common toolchains)
    workspace = os.environ.get('FLUTTER_WORKSPACE')
    if append_to_runtime_env:
        append_to_env_script(workspace, '\n')
        for line in append_to_runtime_env:
            append_to_env_script(workspace, line)


def get_toolchains(platforms):
    """Returns a list of toolchains from the platforms."""
    toolchains = []
    for platform_ in platforms:
        if platform_['type'] == 'toolchain':
            toolchains.append(platform_)
    return toolchains


def get_dependencies(platforms):
    """Returns a list of dependencies from the platforms."""
    dependencies = []
    for platform_ in platforms:
        if platform_['type'] == 'dependency':
            dependencies.append(platform_)
    return dependencies


def get_not_dependencies(platforms):
    """Returns a list of platforms that are not dependencies."""
    not_dependencies = []
    for platform_ in platforms:
        if platform_['type'] != 'dependency':
            not_dependencies.append(platform_)
    return not_dependencies


def setup_platforms(platforms, git_token, cookie_file, plex, enable, disable, enable_plugin, disable_plugin,
                    app_folder):
    """ Sets up each occurring platform defined """

    if plex:
        plex = plex.split(',')

    if enable:
        enable = enable.split(',')

    if disable:
        disable = disable.split(',')

    if enable_plugin:
        enable_plugin = enable_plugin.split(',')

    if disable_plugin:
        disable_plugin = disable_plugin.split(',')

    for toolchain in get_toolchains(platforms):
        setup_toolchain(toolchain, git_token, cookie_file, plex, enable, disable, enable_plugin, disable_plugin,
                        app_folder)

    # iterate over dependencies first
    for dependency in get_dependencies(platforms):
        setup_platform(dependency, git_token, cookie_file, plex, enable, disable, enable_plugin, disable_plugin,
                       app_folder)

        # reset sudo timeout
        validate_sudo_user()

    # iterate over non-dependencies
    for platform_ in get_not_dependencies(platforms):
        setup_platform(platform_, git_token, cookie_file, plex, enable, disable, enable_plugin, disable_plugin,
                       app_folder)

        # reset sudo timeout
        validate_sudo_user()

    print_banner("Platform Setup Complete")


def base64_to_string(b):
    import base64
    return base64.b64decode(b).decode('utf-8')


def get_github_json(token, url):
    """Function to return the JSON of GitHub REST API"""
    import pycurl

    c = pycurl.Curl()
    c.setopt(pycurl.URL, url)
    c.setopt(pycurl.HTTPHEADER, [
        "Accept: application/vnd.github+json", "Authorization: Bearer %s" % token])
    buffer = io.BytesIO()
    c.setopt(pycurl.WRITEDATA, buffer)
    c.perform()
    return json.loads(buffer.getvalue().decode('utf-8'))


def get_github_artifact_list_json(token, url):
    """Function to return the JSON of artifact object array"""

    data = get_github_json(token, url)

    if 'artifacts' in data:
        return data.get('artifacts')

    if 'message' in data:
        print("[get_github_artifact_list_json] GitHub Message: %s" % data.get('message'))
        sys.exit(1)

    return {}


def get_github_workflow_runs(token, owner, repo, workflow):
    """ Gets workflow run list """

    url = "https://api.github.com/repos/%s/%s/actions/workflows/%s/runs" % (
        owner, repo, workflow)

    data = get_github_json(token, url)

    if 'workflow_runs' in data:
        return data.get('workflow_runs')

    if 'message' in data:
        print("[get_github_workflow_runs] GitHub Message: %s" % data.get('message'))
        sys.exit(1)

    return {}


def get_github_workflow_artifacts(token, owner, repo, id_):
    """ Get Workflow Artifact List """

    url = "https://api.github.com/repos/%s/%s/actions/runs/%s/artifacts" % (
        owner, repo, id_)

    data = get_github_json(token, url)

    if 'artifacts' in data:
        return data.get('artifacts')

    if 'message' in data:
        print("[get_github_workflow_artifacts] GitHub Message: %s" % data.get('message'))
        sys.exit(1)

    return {}


def get_workspace_tmp_folder() -> str:
    """ Gets tmp folder path located in workspace"""
    workspace = os.getenv("FLUTTER_WORKSPACE")
    tmp_folder = os.path.join(workspace, '.config', 'flutter_workspace', 'tmp')
    os.makedirs(tmp_folder, exist_ok=True)
    return tmp_folder


def get_github_artifact(token: str, url: str, filename: str) -> str:
    """ Gets artifact via GitHub URL"""

    tmp_file = "%s/%s" % (get_workspace_tmp_folder(), filename)

    headers = ['Authorization: token %s' % token]
    if fetch_https_binary_file(url, tmp_file, True, headers, None, False, None):
        return tmp_file

    return ''


def ubuntu_is_pkg_installed(package: str) -> bool:
    """Ubuntu - checks if package is installed"""

    cmd = "dpkg-query -W --showformat='${Status}' %s" % package
    ps = subprocess.Popen(shlex_quote(cmd), shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    result = ps.communicate()[0]

    if isinstance(result, bytes):
        result = result.decode()

    if 'install ok installed' in result:
        print("Package %s Found" % package)
        return True
    else:
        print("Package %s Not Found" % package)
        return False


def ubuntu_install_pkg_if_not_installed(package):
    """Ubuntu - Installs package if not already installed"""
    if not ubuntu_is_pkg_installed(package):
        print("\n* Installing runtime package dependency: %s" % package)

        cmd = ["sudo", "apt-get", "install", "-y", package]
        subprocess.call(cmd)


def get_dnf_installed(filter_: str) -> str:
    """Returns dnf package list if present, None otherwise"""

    cmd = 'dnf list installed |grep %s' % filter_
    ps = subprocess.Popen(shlex_quote(cmd), shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    result = ps.communicate()[0]

    if isinstance(result, bytes):
        result = result.decode()

    return result


def fedora_is_pkg_installed(package: str) -> bool:
    """Fedora - checks if package is installed"""

    if package in get_dnf_installed(package):
        print("Package %s Found" % package)
        return True
    else:
        print("Package %s Not Found" % package)
        return False


def fedora_install_pkg_if_not_installed(package: str):
    """Fedora - Installs package if not already installed"""
    if not fedora_is_pkg_installed(package):
        print("\n* Installing runtime package dependency: %s" % package)

        cmd = ["sudo", "dnf", "install", "-y", package]
        subprocess.call(cmd)


def is_linux_host_kvm_capable() -> bool:
    """Determine if CPU supports HW Hypervisor support"""
    cmd = 'cat /proc/cpuinfo |egrep "vmx|svm"'
    ps = subprocess.Popen(
        shlex_quote(cmd), shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = ps.communicate()[0]
    if len(output):
        return True
    return False


def get_mac_brew_path() -> str:
    """ Read which brew """
    result = subprocess.run(['which', 'brew'], stdout=subprocess.PIPE)
    return result.stdout.decode('utf-8').rstrip()


def get_mac_brew_prefix(package) -> str:
    """ Read brew prefix for selected package """
    result = subprocess.run(['brew', '--prefix', package], stdout=subprocess.PIPE)
    return result.stdout.decode('utf-8').rstrip()


def activate_python_venv():
    """Activate Python Virtual Environment using venv"""
    workspace = get_ws_folder()
    config_folder = os.path.join(workspace, '.config')
    venv_dir = os.path.join(config_folder, 'venv')

    python_path = os.environ['PYTHON']
    subprocess.check_call([python_path, '-m', 'venv', venv_dir], stdout=subprocess.DEVNULL)
    os.environ['PATH'] = f"{os.path.join(venv_dir, 'bin')}{os.pathsep}{os.environ.get('PATH', '')}"


    # switch python to new path
    python_path = subprocess.check_output(['which', 'python3']).decode().strip()
    os.environ['PYTHON'] = python_path

    cmd = f'{python_path} -m pip install --upgrade pip'.split(' ')
    subprocess.check_output(cmd)


def activate_python_virtualenv():
    """Activate Python Virtual Environment using virtualenv"""
    workspace = get_ws_folder()
    config_folder = os.path.join(workspace, '.config')
    venv_dir = os.path.join(config_folder, 'venv')

    # remove potenial conflict
    if os.environ.get('PYTHONPATH'):
        del os.environ['PYTHONPATH']

    # create virtual environment
    python_path = os.environ['PYTHON']
    subprocess.check_call([python_path, '-m', 'virtualenv', venv_dir], stdout=subprocess.DEVNULL)

    # Determine the correct scripts folder based on platform
    if sys.platform.startswith('win'):
        scripts_folder = 'Scripts'
    else:
        scripts_folder = 'bin'

    # switch to virtualenv
    activate_this_file = os.path.join(venv_dir, scripts_folder, 'activate_this.py')
    exec(compile(open(activate_this_file, 'rb').read(), activate_this_file, 'exec'), dict(__file__=activate_this_file))

    # switch to python in new path
    if sys.platform.startswith('win'):
        python_path = os.path.join(venv_dir, scripts_folder, 'python.exe')
    else:
        python_path = subprocess.check_output(['which', 'python3']).decode().strip()
    os.environ['PYTHON'] = python_path

    cmd = f'{python_path} -m pip install --upgrade pip'.split(' ')
    subprocess.check_output(cmd)
    

def install_minimum_runtime_deps():
    """Install minimum runtime deps to run this script"""
    host_type = get_host_type()

    if host_type == "linux":

        os_release_id = get_freedesktop_os_release_id()

        if os_release_id == 'ubuntu':
            subprocess.check_output(['sudo', 'apt', 'update', '-y'])
            packages = 'sudo apt install --no-install-recommends -y git git-lfs unzip curl python3-dev python3-virtualenv libcurl4-openssl-dev libssl-dev libgtk-3-dev build-essential libcurl4-openssl-dev'.split(
                ' ')
            subprocess.check_output(packages)

        elif os_release_id == 'fedora':
            subprocess.check_output(['sudo', 'dnf', '-y', 'update'])
            packages = 'sudo dnf -y install dnf-plugins-core git git-lfs unzip curl python3-devel python3-virtualenv libcurl-devel openssl-devel gtk3-devel gcc libcurl-devel'.split(
                ' ')
            subprocess.check_output(packages)

    if host_type == "darwin":

        brew_path = get_mac_brew_path()
        if brew_path == '':
            print("brew is required for this script.  Please install.  https://brew.sh")
            sys.exit(1)

        os.environ['NONINTERACTIVE'] = '1'
        os.environ['HOMEBREW_NO_AUTO_UPDATE'] = '1'

        subprocess.run(['brew', 'update'])
        subprocess.run(['brew', 'doctor'])

        packages = 'brew install git git-lfs unzip curl'.split(' ')
        subprocess.check_output(packages)

        # bootstrap with venv
        activate_python_venv()

        cmd = 'python3 -m pip install virtualenv'.split(' ')
        subprocess.check_output(cmd)

    activate_python_virtualenv()

    # Check and install Python packages only if not already installed
    required_packages = [
        ('pycurl', 'pycurl'),
        ('toml', 'toml'), 
        ('python-dotenv', 'dotenv'),
        ('PyYAML', 'yaml')
    ]
    packages_to_install = []
    
    for package_name, import_name in required_packages:
        try:
            __import__(import_name)
            print(f"Package {package_name} is already installed")
        except ImportError:
            print(f"Package {package_name} needs to be installed")
            packages_to_install.append(package_name)
    
    if packages_to_install:
        cmd = ['python3', '-m', 'pip', 'install'] + packages_to_install
        subprocess.check_output(cmd)
    else:
        print("All required Python packages are already installed")


def is_repo(path):
    return os.path.exists(os.path.join(path, ".git"))


def get_random_mac() -> str:
    import random

    mac = [0x00, 0x16, 0x3e,
           random.randint(0x00, 0x7f),
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff)]

    return ':'.join(map(lambda x: "%02x" % x, mac))


def write_env_script_header(workspace):
    """ Write environmental variables to script header"""

    buffer = ""

    if sys.platform.startswith('win'):

        environment_script = os.path.join(workspace, 'setup_env.ps1')

        buffer = r'''
# PowerShell version of setup_env.sh for Windows

# Get the directory of this script
$SCRIPT_PATH = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Remove trailing backslash if present
if ($SCRIPT_PATH.EndsWith('\')) {
    $SCRIPT_PATH = $SCRIPT_PATH.Substring(0, $SCRIPT_PATH.Length)
}

$env:FLUTTER_WORKSPACE = $SCRIPT_PATH
$env:PATH = "$env:FLUTTER_WORKSPACE\\flutter\\bin;$env:PATH"
$env:PUB_CACHE = "$env:FLUTTER_WORKSPACE\\.config\\flutter_workspace\\pub_cache"

Write-Host "********************************************"
Write-Host "* Setting FLUTTER_WORKSPACE to:"
Write-Host "* $env:FLUTTER_WORKSPACE"
Write-Host "********************************************"

'''

    else:

        environment_script = os.path.join(workspace, 'setup_env.sh')

        buffer = '''#!/bin/sh

# Save current directory
ORIGINAL_DIR=$(pwd)

# Get script directory (POSIX-compatible, resolves symlinks if possible)
# Try multiple methods to get the script path
if [ -n "${BASH_SOURCE:-}" ]; then
    # Bash-specific variable (when available)
    SCRIPT_PATH="${BASH_SOURCE[0]}"
elif [ -n "${(%):-%N}" ] 2>/dev/null; then
    # Zsh-specific method
    SCRIPT_PATH="${(%):-%N}"
else
    # Fallback to $0
    SCRIPT_PATH="$0"
fi

# Handle relative paths
case "$SCRIPT_PATH" in
    /*) ;;
    *) SCRIPT_PATH="$PWD/$SCRIPT_PATH";;
esac

# Resolve symlinks (POSIX way)
while [ -h "$SCRIPT_PATH" ]; do
    DIR="$(dirname -- "$SCRIPT_PATH")"
    SYM="$(readlink "$SCRIPT_PATH")"
    case "$SYM" in
        /*) SCRIPT_PATH="$SYM" ;;
        *) SCRIPT_PATH="$DIR/$SYM" ;;
    esac
done

# Get the directory containing the script
SCRIPT_DIR="$(dirname -- "$SCRIPT_PATH")"

# Change to script directory and get absolute path
cd "$SCRIPT_DIR" || exit 1
SCRIPT_PATH="$(pwd)"

# Return to original directory
cd "$ORIGINAL_DIR" || exit 1

echo "SCRIPT_PATH=$SCRIPT_PATH"

export FLUTTER_WORKSPACE="$SCRIPT_PATH"
export PATH="$FLUTTER_WORKSPACE/flutter/bin:$PATH"
export PUB_CACHE="$FLUTTER_WORKSPACE/.config/flutter_workspace/pub_cache"
export XDG_CONFIG_HOME="$FLUTTER_WORKSPACE/.config/flutter"

echo "********************************************"
echo "* Setting FLUTTER_WORKSPACE to:"
echo "* ${FLUTTER_WORKSPACE}"
echo "********************************************"

'''

    with open(environment_script, 'w+', encoding="utf-8") as script:
        script.write(buffer)

def append_to_env_script(workspace, line=None):
    """ Append environmental variables to script """

    if not line:
        return

    if sys.platform.startswith('win'):
        environment_script = os.path.join(workspace, 'setup_env.ps1')
    else:
        environment_script = os.path.join(workspace, 'setup_env.sh')

    if not line.endswith('\n'):
        line += '\n'

    # Don't expand line with PATH or GEN_SNAPSHOT definition, it expands at runtime
    if '$PATH=' not in line and 'PATH=' not in line and \
        '$FLUTTER_WORKSPACE' not in line and \
        'GEN_SNAPSHOT=' not in line:
        # Expand environment variables in the buffer
        print(f'line raw: {line}')
        line = os.path.expanduser(line)
        print(f'line expanduser: {line}')
        line = string.Template(line).safe_substitute(os.environ)
        print(f'cwd safe_substitute: {line}')
        line = os.path.normpath(line)
        print(f'line normpath: {line}')

    with open(environment_script, 'a+', encoding="utf-8") as script:
        script.write(line)

    # Add execute permission for user
    st = os.stat(environment_script)
    os.chmod(environment_script, st.st_mode | stat.S_IXUSR)

def write_env_script_footer(workspace):
    """ Append environmental variables to script footer """

    buffer = '''
flutter doctor -v
'''

    if sys.platform.startswith('win'):
        # append to the script
        environment_script = os.path.join(workspace, 'setup_env.ps1')
    else:
        environment_script = os.path.join(workspace, 'setup_env.sh')

    with open(environment_script, 'a+', encoding="utf-8") as script:
        script.write(buffer)

    # Add execute permission for user
    st = os.stat(environment_script)
    os.chmod(environment_script, st.st_mode | stat.S_IXUSR)

def get_engine_commit(version, hash_):
    """Get matching engine commit hash."""
    import pycurl
    import certifi
    from io import BytesIO

    buffer = BytesIO()
    c = pycurl.Curl()
    c.setopt(
        pycurl.URL, f'https://raw.githubusercontent.com/flutter/flutter/{hash_}/bin/internal/engine.version')
    c.setopt(pycurl.WRITEDATA, buffer)
    c.setopt(pycurl.CAINFO, certifi.where())
    c.perform()
    c.close()

    get_body = buffer.getvalue()

    return version, get_body.decode('utf8').strip()


def get_launch_obj(repo, device_id):
    """returns dictionary of launch target"""
    uri = repo.get('uri')
    repo_name = uri.rsplit('/', 1)[-1]
    repo_name = repo_name.split(".")
    repo_name = repo_name[0]

    pubspec_path = repo.get('pubspec_path')
    if pubspec_path is not None:
        pubspec_path = os.path.join('app', pubspec_path)
        return {"name": "%s (%s)" % (repo_name, device_id), "cwd": pubspec_path, "request": "launch", "type": "dart",
                "deviceId": device_id}
    else:
        return {}


def create_vscode_launch_file(repos: dict, device_ids: list):
    """Creates a default vscode launch.json"""

    workspace = os.getenv("FLUTTER_WORKSPACE")
    vscode_folder = os.path.join(workspace, '.vscode')
    launch_file = os.path.join(vscode_folder, 'launch.json')
    if not os.path.exists(launch_file):
        launch_objs = []
        for repo in repos:
            if 'pubspec_path' in repo:
                for device_id in device_ids:
                    obj = get_launch_obj(repo, device_id)
                    launch_objs.append(obj)

        launch = {'version': '0.2.0', 'configurations': launch_objs}
        os.makedirs(vscode_folder, exist_ok=True)
        with open(launch_file, 'w+', encoding="utf-8") as file:
            json.dump(launch, file, indent=4)


def update_image_by_fastboot(device_id: str, cwd: os.path, artifacts: dict):
    """Updates device using fastboot.  Requires matching device id or returns"""
    print_banner('updating image by fastboot from %s' % cwd)

    subprocess.check_call(['adb', 'version'])
    subprocess.check_call(['fastboot', '--version'])

    adb_device_list = get_process_stdout('sudo adb devices')
    adb_device_not_found = False
    if device_id not in adb_device_list:
        adb_device_not_found = True
        print('[%s] not in adb state' % device_id)

    fastboot_device_list = get_process_stdout('sudo fastboot devices')
    fastboot_device_not_found = False
    if device_id not in fastboot_device_list:
        fastboot_device_not_found = True
        print('[%s] not in fastboot state' % device_id)

    if adb_device_not_found and fastboot_device_not_found:
        print_banner('Device [%s] Not Found' % device_id)
        return

    for i in range(5):
        try:
            fastboot_device_list = get_process_stdout("sudo fastboot devices")
            fastboot_device_list = fastboot_device_list.split('\n')
            if fastboot_device_list == ['']:
                print('no fastboot devices, reboot as bootloader')
                cmd = ["sudo", "adb", "reboot", "bootloader"]
                print(cmd)
                subprocess.check_call(cmd)
                time.sleep(1)
            else:
                print('found fastboot device!! ')
                break

        except Exception as e:
            print(f"Attempt {i + 1} failed: {e}")
            time.sleep(1)
    else:
        print("Operation failed after 5 attempts.")

    artifact_list = artifacts.get('x86_64')
    for artifact in artifact_list:
        partition = artifact.get('partition')
        endpoint = artifact.get('endpoint')

        if partition is None:
            continue
        if endpoint is None:
            continue

        endpoint = os.path.expandvars(endpoint)
        filename = get_filename_from_url(endpoint)
        filepath = os.path.join(cwd, filename)

        if os.path.exists(filepath):
            cmd = ["sudo", "fastboot", "flash", partition, filepath]
            print(cmd)
            subprocess.check_call(cmd, cwd=cwd)

    cmd = ["sudo", "fastboot", "reboot"]
    print(cmd)
    subprocess.check_call(cmd, cwd=cwd)


def validate_fastboot_req(device_id: str, platform_: dict):
    if 'runtime' not in platform_:
        print('Missing runtime token in platform')
        return

    runtime = platform_['runtime']
    if 'artifacts' not in runtime:
        print('Missing artifact token in runtime')
        return

    artifacts = runtime['artifacts']

    if 'http' not in artifacts:
        print('Missing http token in artifacts')
        return
    http = artifacts['http']

    if 'artifacts' not in http:
        print('Missing artifact token in http')
        return

    if 'env' in platform_:
        handle_env(platform_['env'], None)

    platform_id = platform_['id']
    working_dir = get_platform_working_dir(platform_id)
    artifacts_dir = os.path.join(working_dir, 'artifacts')
    update_image_by_fastboot(device_id, artifacts_dir, http.get('artifacts'))


def flash_fastboot(platform_id: str, device_id: str, platforms: dict):
    if not platform_id:
        print('Missing platform_id')
        return

    for platform_ in platforms:
        current_platform_id = platform_.get('id')
        if platform_id == current_platform_id:
            validate_fastboot_req(device_id, platform_)
            break


def flash_mask_rom(platform_id: str, _: str, platforms: dict):
    print_banner("Flash with Mask ROM")
    if not platform_id:
        print('platform_id is None')
        return

    for platform_ in platforms:
        if platform_id == platform_.get('id'):
            print("Mask ROM Flash [%s]" % platform_id)

            working_dir = get_platform_working_dir(platform_id)

            if 'env' in platform_:
                handle_env(platform_.get('env'), None)

            runtime = platform_.get('runtime')
            flash_cmds = runtime.get('flash_mask_rom')

            handle_commands_obj(flash_cmds, working_dir)
            break


def flutter_analyze_git_commits():
    if not os.path.exists('.git'):
        print('Directory does not contain .git')
        return

    if "FLUTTER_WORKSPACE" not in os.environ:
        print('The workspace environment is not set')
        return

    stdout = get_process_stdout('git rev-list HEAD')
    commits = stdout.split('\n')
    for commit in commits:
        cmd = ['git', 'checkout', '--force', commit]
        subprocess.call(cmd)
        cmd = ['flutter', 'analyze', '.']
        try:
            subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            print("*** Commit %s does not work." % commit)
            continue

        print('*** Found working commit: %s' % commit)
        break


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_ctrl_c)
    os.environ['PYTHON'] = sys.executable
    main()
