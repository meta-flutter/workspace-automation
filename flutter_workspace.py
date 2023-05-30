#!/usr/bin/env python3

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


import errno
import io
import json
import os
import platform
import shlex
import signal
import subprocess
import sys
import time
import zipfile
from platform import system
from sys import stderr as stream

# use kiB's
kb = 1024


def print_banner(text):
    print('*' * (len(text) + 6))
    print("** %s **" % text)
    print('*' * (len(text) + 6))


def handle_ctrl_c(_signal, _frame):
    sys.exit("Ctl+C - Closing")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--clean', default=False,
                        action='store_true', help='Wipes workspace clean')
    parser.add_argument('--config', default='configs', type=str,
                        help='Selects custom workspace configuration folder')
    parser.add_argument('--flutter-version', default='', type=str,
                        help='Select flutter version.  Overrides config file key:'
                             ' flutter-version')
    parser.add_argument('--github-token', default='', type=str,
                        help='Set github-token.  Overrides _globals.json key/value')
    parser.add_argument('--cookie-file', default='', type=str,
                        help='Set cookie-file to use.  Overrides _globals.json key/value')
    parser.add_argument('--fetch-engine', default=False,
                        action='store_true', help='Fetch Engine artifacts')
    parser.add_argument('--version-files', default='', type=str,
                        help='Create JSON files correlating Flutter SDK to Engine and Dart commits')
    parser.add_argument('--find-working-commit', default=False, action='store_true',
                        help='Use to finding GIT commit where flutter analyze returns true')
    parser.add_argument('--plex', default='', type=str,
                        help='Platform Load Excludes')
    parser.add_argument('--fastboot', default='', type=str,
                        help='Update the selected platform using fastboot')
    parser.add_argument('--mask-rom', default='', type=str,
                        help='Update the selected platform using Mask ROM')
    parser.add_argument('--device-id', default='', type=str, help='device id for flashing')

    parser.add_argument('--stdin-file', default='', type=str,
                        help='Use for passing stdin for debugging')
    args = parser.parse_args()

    #
    # Find GIT Commit where flutter analyze returns true
    #
    if args.find_working_commit:
        flutter_analyze_git_commits()
        return

    # check python version
    check_python_version()

    # reset sudo timestamp
    subprocess.check_call(['sudo', '-k'], stdout=subprocess.DEVNULL)

    # validate sudo user timestamp
    if os.path.exists(args.stdin_file):
        stdin_file = open(args.stdin_file)
        subprocess.check_call(['sudo', '-S', '-v'],
                              stdout=subprocess.DEVNULL, stdin=stdin_file)
    else:
        subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)

    #
    # Target Folder
    #
    if "FLUTTER_WORKSPACE" in os.environ:
        workspace = os.environ.get('FLUTTER_WORKSPACE')
    else:
        workspace = os.getcwd()

    print_banner("Setting up Flutter Workspace in: %s" % workspace)

    #
    # Install minimum package
    #
    install_minimum_runtime_deps()

    #
    # Install required modules
    #
    # upgrade pip
    python = sys.executable
    subprocess.check_call([python, '-m', 'pip', 'install',
                           '--upgrade', 'pip'], stdout=subprocess.DEVNULL)

    #
    # Control+C handler
    #
    signal.signal(signal.SIGINT, handle_ctrl_c)

    #
    # Create Workspace
    #
    is_exist = os.path.exists(workspace)
    if not is_exist:
        os.makedirs(workspace)

    if os.path.exists(workspace):
        os.environ['FLUTTER_WORKSPACE'] = workspace

    #
    # Fetch Engine Artifacts
    #
    if args.fetch_engine:
        print_banner("Fetching Engine Artifacts")
        get_flutter_engine_runtime(True)
        return

    #
    # Version Files
    #
    if args.version_files:
        print_banner("Generating Version files")
        get_version_files(args.version_files)
        return

    #
    # Workspace Configuration
    #
    config = get_workspace_config(args.config)
    globals_ = config.get('globals')

    platforms = config.get('platforms')
    for platform_ in platforms:
        if not validate_platform_config(platform_):
            print("Invalid platform configuration")
            exit(1)

    app_folder = os.path.join(workspace, 'app')
    flutter_sdk_folder = os.path.join(workspace, 'flutter')

    config_folder = os.path.join(workspace, '.config')
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
        flash_fastboot(args.fastboot, args.device_id, platforms)
        return

    #
    # Mask ROM
    #
    if args.mask_rom:
        flash_mask_rom(args.mask_rom, args.device_id, platforms)
        return

    #
    # App folder setup
    #
    is_exist = os.path.exists(app_folder)
    if not is_exist:
        os.makedirs(app_folder)

    get_workspace_repos(app_folder, config)

    #
    # Get Flutter SDK
    #
    if args.flutter_version:
        flutter_version = args.flutter_version
    else:
        if 'flutter-version' in globals_:
            flutter_version = globals_.get('flutter-version')
        else:
            flutter_version = "master"

    print_banner("Flutter Version: %s" % flutter_version)
    flutter_sdk_path = get_flutter_sdk(flutter_version)
    flutter_bin_path = os.path.join(flutter_sdk_path, 'bin')

    # force tool rebuild
    force_tool_rebuild(flutter_sdk_folder)

    # Enable custom devices in dev and stable
    if flutter_version != "master":
        patch_flutter_sdk(flutter_sdk_folder)

    #
    # Configure Workspace
    #

    os.environ['PATH'] = '%s:%s' % (os.environ.get('PATH'), flutter_bin_path)
    os.environ['PUB_CACHE'] = os.path.join(os.environ.get('FLUTTER_WORKSPACE'), '.config', 'flutter_workspace',
                                           'pub_cache')
    os.environ['XDG_CONFIG_HOME'] = os.path.join(
        os.environ.get('FLUTTER_WORKSPACE'), '.config', 'flutter')

    print("PATH=%s" % os.environ.get('PATH'))
    print("PUB_CACHE=%s" % os.environ.get('PUB_CACHE'))
    print("XDG_CONFIG_HOME=%s" % os.environ.get('XDG_CONFIG_HOME'))

    #
    # Trigger upgrade on Channel if version is all letters
    #
    if flutter_version.isalpha():
        cmd = ["flutter", "upgrade", flutter_version]
        print_banner("Upgrading `%s` Channel" % flutter_version)
        subprocess.check_call(cmd, cwd=flutter_sdk_path)

    #
    # Configure SDK
    #
    configure_flutter_sdk()

    #
    # Flutter Engine Runtime
    #
    get_flutter_engine_runtime(clean_workspace)

    #
    # Create environmental setup script
    #
    write_env_script_header(workspace)

    #
    # Setup Platform(s)
    #
    github_token = globals_.get('github_token')
    if args.github_token:
        github_token = args.github_token

    cookie_file = globals_.get('cookie_file')
    if args.cookie_file:
        cookie_file = args.cookie_file

    setup_platforms(platforms, github_token, cookie_file, args.plex)

    #
    # Display the custom devices list
    #
    if flutter_version == "master":
        cmd = ['flutter', 'custom-devices', 'list']
        subprocess.check_call(cmd)

    #
    # Done
    #
    print_banner("Setup Flutter Workspace - Complete")


def test_internet_connection():
    """Test internet by connecting to nameserver"""
    import pycurl

    c = pycurl.Curl()
    c.setopt(pycurl.URL, "https://dns.google")
    c.setopt(pycurl.FOLLOWLOCATION, 0)
    c.setopt(pycurl.CONNECTTIMEOUT, 5)
    c.setopt(pycurl.NOSIGNAL, 1)
    c.setopt(pycurl.NOPROGRESS, 1)
    c.setopt(pycurl.NOBODY, 1)
    try:
        c.perform()
    except:
        pass

    res = False
    if c.getinfo(pycurl.RESPONSE_CODE) == 200:
        res = True

    return res


def make_sure_path_exists(path):
    try:
        os.makedirs(path)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise


def clear_folder(dir_):
    """ Clears folder specified """
    import shutil
    if os.path.exists(dir_):
        shutil.rmtree(dir_)


def get_workspace_config(path):
    """ Returns workspace config """

    if os.path.isdir(path):

        data = {'globals': None, 'repos': None, 'platforms': []}

        import glob
        for filename in glob.glob(os.path.join(path, '*.json')):

            with open(os.path.join(os.getcwd(), filename), 'r') as f:

                _head, tail = os.path.split(filename)

                if tail == '_repos.json':
                    try:
                        data['repos'] = json.load(f)
                    except json.decoder.JSONDecodeError:
                        print("Invalid JSON in %s" % f)
                        exit(1)

                elif tail == '_globals.json':
                    try:
                        data['globals'] = json.load(f)
                    except json.decoder.JSONDecodeError:
                        print("Invalid JSON in %s" % f)
                        exit(1)

                else:
                    try:
                        platform_ = json.load(f)
                        if 'load' in platform_:
                            if not platform_['load']:
                                continue
                        data['platforms'].append(platform_)
                    except json.decoder.JSONDecodeError:
                        print("Invalid JSON in %s" % f)
                        exit(1)

    elif os.path.isfile(path):
        with open(path, 'r') as f:
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
            if 'flutter_runtime' not in platform_:
                print_banner(
                    "Missing 'flutter_runtime' key in platform config")
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
            if 'flutter_runtime' not in platform_:
                print_banner(
                    "Missing 'flutter_runtime' key in platform config")
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
            if 'flutter_runtime' not in platform_:
                print_banner(
                    "Missing 'flutter_runtime' key in platform config")
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

        print("Platform ID: %s" % (platform_['id']))

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

    git_folder = os.path.join(base_folder, repo_name)

    git_folder_git = os.path.join(base_folder, repo_name, '.git')

    is_exist = os.path.exists(git_folder_git)
    if not is_exist:

        is_exist = os.path.exists(git_folder)
        if is_exist:
            os.removedirs(git_folder)

        cmd = ['git', 'clone', uri, '-b', branch, repo_name]
        subprocess.check_call(cmd, cwd=base_folder)

    if rev:

        cmd = ['git', 'reset', '--hard', rev]
        subprocess.check_call(cmd, cwd=git_folder)

    else:

        cmd = ['git', 'reset', '--hard']
        subprocess.check_call(cmd, cwd=git_folder)

        cmd = ['git', 'pull', '--all']
        subprocess.check_call(cmd, cwd=git_folder)

    # get all submodules
    git_submodule_file = os.path.join(base_folder, repo_name, '.gitmodules')
    if os.path.exists(git_submodule_file):
        cmd = ['git', 'submodule', 'update', '--init', '--recursive']
        subprocess.check_call(cmd, cwd=git_folder)


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
            subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)

        for _future in concurrent.futures.as_completed(futures):
            subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)

    print_banner("Repos Cloned")

    # reset sudo timeout
    subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)

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


def get_flutter_settings_folder():
    """ Returns the path of the Custom Config json file """

    if "XDG_CONFIG_HOME" in os.environ:
        settings_folder = os.path.join(os.environ.get('XDG_CONFIG_HOME'))
    else:
        settings_folder = os.path.join(
            os.environ.get('HOME'), '.config', 'flutter')

    make_sure_path_exists(settings_folder)

    return settings_folder


def get_flutter_custom_config_path():
    """ Returns the path of the Flutter Custom Config json file """

    folder = get_flutter_settings_folder()
    # print("folder: %s" % folder)
    return os.path.join(folder, 'custom_devices.json')


def get_flutter_custom_devices():
    """ Returns the Flutter custom_devices.json as dict """

    custom_config = get_flutter_custom_config_path()
    if os.path.exists(custom_config):

        f = open(custom_config)
        try:
            data = json.load(f)
        except json.decoder.JSONDecodeError:
            # in case json is invalid
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

        f = open(custom_config, "r")
        try:
            obj = json.load(f)
        except json.decoder.JSONDecodeError:
            print_banner("Invalid JSON in %s" %
                         custom_config)  # in case json is invalid
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

        with open(custom_config, "w") as outfile:
            json.dump(custom_devices, outfile, indent=2)

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

        token = '${FLUTTER_WORKSPACE}'

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
                token, workspace, device['postBuild'])

        if device.get('runDebug'):
            device['runDebug'] = patch_string_array(
                token, workspace, device['runDebug'])

        token = '${BUNDLE_FOLDER}'
        if device.get('install'):
            device['install'] = patch_string_array(
                token, bundle_folder, device['install'])

    return devices


def fixup_custom_device(obj):
    """ Patch custom device string environmental variables to use literal values """

    obj['id'] = os.path.expandvars(obj['id'])
    obj['label'] = os.path.expandvars(obj['label'])
    obj['sdkNameAndVersion'] = os.path.expandvars(obj['sdkNameAndVersion'])
    obj['platform'] = os.path.expandvars(obj['platform'])
    obj['ping'] = os.path.expandvars(obj['ping'])
    obj['ping'] = shlex.split(obj['ping'])
    obj['pingSuccessRegex'] = os.path.expandvars(obj['pingSuccessRegex'])
    if obj['postBuild']:
        obj['postBuild'] = os.path.expandvars(obj['postBuild'])
        obj['postBuild'] = shlex.split(obj['postBuild'])
    if obj['install']:
        obj['install'] = os.path.expandvars(obj['install'])
        obj['install'] = shlex.split(obj['install'])
    if obj['uninstall']:
        obj['uninstall'] = os.path.expandvars(obj['uninstall'])
        obj['uninstall'] = shlex.split(obj['uninstall'])
    if obj['runDebug']:
        obj['runDebug'] = os.path.expandvars(obj['runDebug'])
        obj['runDebug'] = shlex.split(obj['runDebug'])
    if obj['forwardPort']:
        obj['forwardPort'] = os.path.expandvars(obj['forwardPort'])
        obj['forwardPort'] = shlex.split(obj['forwardPort'])
    if obj['forwardPortSuccessRegex']:
        obj['forwardPortSuccessRegex'] = os.path.expandvars(
            obj['forwardPortSuccessRegex'])
    if obj['screenshot']:
        obj['screenshot'] = os.path.expandvars(obj['screenshot'])
        obj['screenshot'] = shlex.split(obj['screenshot'])

    return obj


def add_flutter_custom_device(device_config, flutter_runtime):
    """ Add a single Flutter custom device from json string """

    if not validate_custom_device_config(device_config):
        exit(1)

    # print("Adding custom-device: %s" % device_config)

    custom_devices_file = get_flutter_custom_config_path()

    new_device_list = []
    if os.path.exists(custom_devices_file):

        f = open(custom_devices_file, "r")
        try:
            obj = json.load(f)
        except json.decoder.JSONDecodeError:
            print_banner("Invalid JSON in %s" %
                         custom_devices_file)  # in case json is invalid
            exit(1)
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
    with open(custom_devices_file, "w+") as outfile:
        json.dump(custom_devices, outfile, indent=4)

    return


def add_flutter_custom_device_ex(custom_device, _flutter_runtime):
    """ Add a single Flutter custom device from json string """

    if not validate_custom_device_config(custom_device):
        sys.exit("Invalid Custom Device configuration")

    device_config = fixup_custom_device(custom_device)
    # print("Adding custom-device: %s" % device_config)

    custom_devices_file = get_flutter_custom_config_path()

    new_device_list = []
    if os.path.exists(custom_devices_file):

        f = open(custom_devices_file, "r")
        try:
            obj = json.load(f)
        except json.decoder.JSONDecodeError:
            print_banner("Invalid JSON in %s" %
                         custom_devices_file)  # in case json is invalid
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
    with open(custom_devices_file, "w+") as outfile:
        json.dump(custom_devices, outfile, indent=4)

    return


def handle_custom_devices(platform_):
    """ Updates the custom_devices.json with platform config """

    if "custom-device" not in platform_:
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
        platform_['custom-device'], platform_['flutter_runtime'])


def configure_flutter_sdk():
    settings = {"enable-web": False, "enable-android": False, "enable-ios": False, "enable-fuchsia": False,
                "enable-custom-devices": True}

    host = get_host_type()
    if host == 'darwin':
        settings['enable-linux-desktop'] = False
        settings['enable-macos-desktop'] = True
        settings['enable-windows-desktop'] = False
    elif host == 'linux':
        settings['enable-linux-desktop'] = True
        settings['enable-macos-desktop'] = False
        settings['enable-windows-desktop'] = False
    elif host == 'windows':
        settings['enable-linux-desktop'] = False
        settings['enable-macos-desktop'] = False
        settings['enable-windows-desktop'] = True

    settings_file = os.path.join(get_flutter_settings_folder(), 'settings')

    with open(settings_file, "w+") as outfile:
        json.dump(settings, outfile, indent=2)

    cmd = ['flutter', 'config', '--no-analytics']
    subprocess.check_call(cmd)
    cmd = ['dart', '--disable-analytics']
    subprocess.check_call(cmd)
    cmd = ['flutter', 'doctor']
    subprocess.check_call(cmd)


def force_tool_rebuild(flutter_sdk_folder):
    tool_script = os.path.join(
        flutter_sdk_folder, 'bin', 'cache', 'flutter_tools.snapshot')

    if os.path.exists(tool_script):
        print_banner("Cleaning Flutter Tool")

        cmd = ["rm", tool_script]
        subprocess.check_call(cmd, cwd=flutter_sdk_folder)


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


# Check for flutter SDK path. Pull if exists. Create dir and clone sdk if not.
def get_flutter_sdk(version):
    """ Get Flutter SDK clone """

    workspace = os.environ.get('FLUTTER_WORKSPACE')

    flutter_sdk_path = os.path.join(workspace, 'flutter')

    #
    # GIT repo
    #
    if is_repo(flutter_sdk_path):

        print('Checking out %s' % version)
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

    engine_version_file = os.path.join(
        flutter_sdk_path, 'bin/internal/engine.version')

    if not os.path.exists(engine_version_file):
        sys.exit("Missing Flutter SDK")

    with open(engine_version_file) as f:
        engine_version = f.read()
        print(f"Engine Version: {engine_version.strip()}")

    return engine_version.strip()


def get_process_stdout(cmd):
    process = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, universal_newlines=True)
    ret = ""
    for line in process.stdout:
        ret += str(line)
    process.wait()
    print(ret)
    return ret


def get_freedesktop_os_release() -> dict:
    """ Read /etc/os-release into dictionary """

    with open("/etc/os-release") as f:
        d = {}
        for line in f:
            line = line.strip()
            k, v = line.rstrip().split("=")
            d[k] = v.strip('"')
        return d


def get_freedesktop_os_release_name() -> str:
    """Returns OS Release NAME value"""
    return get_freedesktop_os_release().get('NAME').lower().rstrip()


def get_freedesktop_os_release_id() -> str:
    """Returns OS Release ID value"""
    return get_freedesktop_os_release().get('ID').rstrip()


def get_host_type() -> str:
    """Returns host system"""
    return system().lower().rstrip()


def fetch_https_progress(download_t, download_d, _upload_t, _upload_d):
    """callback function for pycurl.XFERINFOFUNCTION"""
    stream.write('Progress: {}/{} kiB ({}%)\r'.format(str(int(download_d / kb)), str(int(download_t / kb)),
                                                      str(int(download_d / download_t * 100) if download_t > 0 else 0)))
    stream.flush()


def fetch_https_binary_file(url, filename, redirect, headers, cookie_file, netrc):
    """Fetches binary file via HTTPS"""
    import pycurl
    import time

    retries_left = 3
    delay_between_retries = 5  # seconds
    success = False

    c = pycurl.Curl()
    c.setopt(pycurl.URL, url)
    c.setopt(pycurl.CONNECTTIMEOUT, 30)
    c.setopt(pycurl.NOSIGNAL, 1)
    c.setopt(pycurl.NOPROGRESS, False)
    c.setopt(pycurl.XFERINFOFUNCTION, fetch_https_progress)

    if headers:
        c.setopt(pycurl.HTTPHEADER, headers)

    if redirect:
        c.setopt(pycurl.FOLLOWLOCATION, 1)
        c.setopt(pycurl.AUTOREFERER, 1)
        c.setopt(pycurl.MAXREDIRS, 255)

    if cookie_file:
        cookie_file = os.path.expandvars(cookie_file)
        print("Using cookie file: %s" % cookie_file)
        c.setopt(pycurl.COOKIEFILE, cookie_file)

    if netrc:
        c.setopt(pycurl.NETRC, 1)

    while retries_left > 0:
        try:
            with open(filename, 'wb') as f:
                c.setopt(pycurl.WRITEFUNCTION, f.write)
                c.perform()

            success = True
            break

        except pycurl.error:
            retries_left -= 1
            time.sleep(delay_between_retries)

    status = c.getinfo(pycurl.HTTP_CODE)

    c.close()
    os.sync()

    if not redirect and status == 302:
        print_banner("Download Status: %d" % status)
        return False
    if not status == 200:
        print_banner("Download Status: %d" % status)
        return False

    return success


def get_host_machine_arch():
    return platform.machine()


def get_google_flutter_engine_url():
    workspace = os.environ.get('FLUTTER_WORKSPACE')
    if not workspace:
        sys.exit("FLUTTER_WORKSPACE not set")

    flutter_sdk_path = os.path.join(workspace, 'flutter')
    arch = get_host_machine_arch()

    engine_version = get_flutter_engine_version(flutter_sdk_path)
    url = ''
    if arch == 'x86_64':
        url = 'https://storage.googleapis.com/flutter_infra_release/flutter/%s/linux-x64/linux-x64-embedder' % \
              engine_version
    elif arch == 'arm64':
        url = 'https://storage.googleapis.com/flutter_infra_release/flutter/%s/linux-arm64/artifacts.zip' % \
              engine_version
    return url, engine_version


def compare_sha256(archive_path: str, sha256_file: str) -> bool:
    if not os.path.exists(archive_path):
        return False

    if not os.path.exists(sha256_file):
        return False

    archive_sha256_val = get_sha256sum(archive_path)

    with open(sha256_file, 'r') as f:
        sha256_file_val = f.read().replace('\n', '')

        if archive_sha256_val == sha256_file_val:
            return True

    return False


def write_sha256_file(cwd: str, filename: str):
    file = os.path.join(cwd, filename)
    sha256_val = get_sha256sum(file)
    sha256_file = os.path.join(cwd, filename + '.sha256')

    with open(sha256_file, 'w+') as f:
        f.write(sha256_val)


def get_flutter_engine_runtime(clean_workspace):
    """Downloads Flutter Engine Runtime"""

    base_url, engine_version = get_google_flutter_engine_url()

    _head, tail = os.path.split(base_url)
    filename = tail + '.zip'

    cwd = get_platform_working_dir('flutter-engine')

    cwd_engine = os.path.join(cwd, engine_version)

    archive_file = os.path.join(cwd_engine, filename)
    sha256_file = os.path.join(cwd_engine, filename + '.sha256')

    if not compare_sha256(archive_file, sha256_file):
        print_banner("Downloading Engine artifact")
        make_sure_path_exists(cwd_engine)
        download_https_file(cwd_engine, base_url, filename,
                            None, None, None, None, None)
        write_sha256_file(cwd_engine, archive_file)
    else:
        print_banner("Skipping Engine artifact download")

    bundle_folder = os.path.join(cwd, 'bundle')
    os.environ['BUNDLE_FOLDER'] = bundle_folder

    if clean_workspace:
        if os.path.exists(bundle_folder):
            cmd = ["rm", "-rf", bundle_folder]
            subprocess.check_output(cmd, cwd=cwd)

    lib_folder = os.path.join(bundle_folder, 'lib')
    make_sure_path_exists(lib_folder)

    data_folder = os.path.join(bundle_folder, 'data')
    make_sure_path_exists(data_folder)

    workspace = os.environ.get('FLUTTER_WORKSPACE')
    flutter_sdk_path = os.path.join(workspace, 'flutter')

    host_type = get_host_type()

    icudtl_source = os.path.join(
        flutter_sdk_path,
        "bin/cache/artifacts/engine/%s/icudtl.dat" %
        'linux-x64'
        if host_type == 'linux'
        else 'darwin-x64')

    if not os.path.exists(icudtl_source):
        cmd = ["flutter", "doctor", "-v"]
        subprocess.check_call(cmd, cwd=flutter_sdk_path)

    icudtl_source = os.path.join(
        flutter_sdk_path,
        "bin/cache/artifacts/engine/%s-x64/icudtl.dat" %
        host_type)

    subprocess.check_call(["cp", icudtl_source, "%s/" % data_folder])

    with zipfile.ZipFile(archive_file, "r") as zip_ref:
        zip_ref.extractall(lib_folder)

    if host_type == 'linux':
        cmd = ["rm", "flutter_embedder.h"]
        subprocess.check_call(cmd, cwd=lib_folder)


def handle_conditionals(conditionals, cwd):
    if not conditionals:
        return

    print(conditionals)
    for condition in conditionals:
        path = os.path.expandvars(condition['path'])
        print(path)

        if not os.path.exists(path):
            print("** Conditionals **")
            for cmd_str in condition['cmds']:
                cmd_str = os.path.expandvars(cmd_str)
                cmd_arr = shlex.split(cmd_str)
                print(cmd_arr)
                subprocess.call(cmd_arr, cwd=cwd)


def handle_pre_requisites(obj, cwd):
    if not obj:
        return

    host_machine_arch = get_host_machine_arch()

    if host_machine_arch in obj:
        host_specific_pre_requisites = obj[host_machine_arch]

        host_type = get_host_type()

        if host_type == "linux":
            host_type = get_freedesktop_os_release_id()

        if host_specific_pre_requisites.get(host_type):
            distro = host_specific_pre_requisites[host_type]
            handle_conditionals(distro.get('conditionals'), cwd)
            handle_commands(distro.get('cmds'), cwd)
        else:
            print('handle_pre_requisites: Not supported')


def get_md5sum(file):
    """Return md5sum of specified file"""
    import hashlib

    if not os.path.exists(file):
        return ''

    md5_hash = hashlib.md5()
    with open(file, "rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)

    return md5_hash.hexdigest()


def get_sha1sum(file):
    """Return sha1sum of specified file"""
    import hashlib

    if not os.path.exists(file):
        return ''

    sha1_hash = hashlib.sha1()
    with open(file, "rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha1_hash.update(byte_block)

    return sha1_hash.hexdigest()


def get_sha256sum(file):
    """Return sha256sum of specified file"""
    import hashlib

    if not os.path.exists(file):
        return ''

    sha256_hash = hashlib.sha256()
    with open(file, "rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    return sha256_hash.hexdigest()


def download_https_file(cwd, url, file, cookie_file, netrc, md5, sha1, sha256):
    download_filepath = os.path.join(cwd, file)

    sha256_file = os.path.join(cwd, file + '.sha256')
    if compare_sha256(download_filepath, sha256_file):
        print("%s exists, skipping download" % download_filepath)
        return

    if os.path.exists(download_filepath):
        if md5:
            # don't download if md5 is good
            if md5 == get_md5sum(download_filepath):
                print("** Using %s" % download_filepath)
                return
            else:
                os.remove(download_filepath)
        elif sha1:
            # don't download if sha1 is good
            if sha1 == get_sha1sum(download_filepath):
                print("** Using %s" % download_filepath)
                return
            else:
                os.remove(download_filepath)
        elif sha256:
            # don't download if sha256 is good
            if sha256 == get_sha256sum(download_filepath):
                print("** Using %s" % download_filepath)
                return
            else:
                os.remove(download_filepath)

    print("** Downloading %s via %s" % (file, url))
    res = fetch_https_binary_file(
        url, download_filepath, False, None, cookie_file, netrc)
    if not res:
        os.remove(download_filepath)
        print_banner("Failed to download %s" % file)
        return

    if os.path.exists(download_filepath):
        if md5:
            expected_md5 = get_md5sum(download_filepath)
            if md5 != expected_md5:
                sys.exit('Download artifact %s md5: %s does not match expected: %s' %
                         (download_filepath, md5, expected_md5))
        elif sha1:
            expected_sha1 = get_sha1sum(download_filepath)
            if sha1 != expected_sha1:
                sys.exit('Download artifact %s sha1: %s does not match expected: %s' %
                         (download_filepath, md5, expected_sha1))
        elif sha256:
            expected_sha256 = get_sha256sum(download_filepath)
            if sha256 != expected_sha256:
                sys.exit('Download artifact %s sha256: %s does not match expected: %s' %
                         (download_filepath, sha256, expected_sha256))

    write_sha256_file(cwd, file)


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

    file = open(netrc, "r")
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
        sys.exit("Fix ~/.netrc to continue")
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
                filename = get_filename_from_url(base_url)

                print(base_url)
                print(filename)

                futures.append(executor.submit(download_https_file, cwd, base_url, filename, cookie_file,
                                               netrc, artifact.get('md5'), artifact.get('sha1'),
                                               artifact.get('sha256')))
                subprocess.check_call(
                    ['sudo', '-v'], stdout=subprocess.DEVNULL)

            for future in concurrent.futures.as_completed(futures):
                _res = future.result()
                subprocess.check_call(
                    ['sudo', '-v'], stdout=subprocess.DEVNULL)


def handle_commands_obj(cmd_list, cwd):
    if not cmd_list:
        return

    for obj in cmd_list:
        if 'cmds' not in obj:
            continue

        host_type = get_host_type()
        if host_type == 'linux':
            host_type = get_freedesktop_os_release_id()

        local_env = os.environ.copy()

        # sandbox variables to commands
        if host_type in obj:
            cmds = obj[host_type]
            if 'env' in cmds:
                handle_env(cmds.get('env'), None)

        if 'env' in obj:
            handle_env(obj.get('env'), local_env)

        if 'cwd' in obj:
            cwd = os.path.expandvars(obj.get('cwd'))
            print('cwd: ', cwd)
            make_sure_path_exists(cwd)

        shell_ = False
        if 'shell' in obj:
            shell_ = obj.get('shell')

        cmds = obj.get('cmds')
        for cmd in cmds:
            expanded_cmd = os.path.expandvars(cmd)
            cmd_arr = shlex.split(expanded_cmd)
            print('cmd: %s' % cmd_arr)
            subprocess.check_call(cmd_arr, cwd=cwd, env=local_env, shell=shell_)


def handle_commands(cmds, cwd):
    if cmds:
        for cmd in cmds:
            expanded_cmd = os.path.expandvars(cmd)
            cmd_arr = shlex.split(expanded_cmd)
            subprocess.check_call(cmd_arr, cwd=cwd)


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


def handle_docker_obj(obj, _host_machine_arch, cwd):
    if not obj:
        return

    # handle_docker_registry(obj.get('registry'))
    docker_compose_stop(obj.get('docker-compose-yml-dir'))
    handle_commands(obj.get('post_cmds'), cwd)
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

    if not qemu.get(host_machine_arch):
        sys.exit("Configuration not specified for this host machine architecture")
    if not qemu.get('cmd'):
        sys.exit("Command not specified")

    if qemu.get('extra'):
        extra = ''
        host_type = get_host_type()
        if 'linux' == host_type:
            host_type = get_freedesktop_os_release_id()
            if is_linux_host_kvm_capable():
                extra = '-enable-kvm '
        if host_type not in qemu['extra']:
            sys.exit("Extra parameters not specified for this host type")
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

    artifacts_dir = os.environ['ARTIFACTS_DIR']
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
        terminal_cmd = format(
            'gnome-terminal -- bash -c \"%s %s\"' % (cmd, args))
        # terminal_cmd = cmd + " " + args
    elif host_type == "darwin":
        apple_script_filename = 'run-' + platform_id + '.scpt'
        terminal_cmd = format(
            'osascript ${FLUTTER_WORKSPACE}/%s' % apple_script_filename)
        apple_script_file = os.path.join(
            flutter_workspace, apple_script_filename)
        with open(apple_script_file, 'w+') as f:
            f.write(format(env_qemu_applescript % (cmd, args)))

    env_script = os.path.join(flutter_workspace, 'setup_env.sh')
    with open(env_script, 'a') as f:
        f.write(env_qemu % (
            platform_id,
            platform_id,
            os.environ['CONTAINER_SSH_PORT'],
            os.environ['CONTAINER_SSH_PORT'],
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
                    if downloaded_file is None:
                        print_banner("Failed to download %s" % filename)
                        continue

                    print("Downloaded: %s" % downloaded_file)

                    with zipfile.ZipFile(downloaded_file, "r") as zip_ref:
                        zip_ref.extractall(str(cwd))

                    cmd = ["rm", downloaded_file]
                    subprocess.check_output(cmd)
                    continue

        if post_process:
            for cmd in post_process:
                expanded_cmd = os.path.expandvars(cmd)
                cmd_arr = shlex.split(expanded_cmd)
                subprocess.call(cmd_arr, cwd=cwd, env=os.environ)


def handle_artifacts_obj(obj, host_machine_arch, cwd, git_token, cookie_file):
    if not obj:
        return

    artifacts = os.path.join(cwd, 'artifacts')
    make_sure_path_exists(artifacts)
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

    for dotenv_file in dotenv_files:
        dotenv_path = Path(dotenv_file)
        load_dotenv(dotenv_path=dotenv_path)
        print("Loaded: %s" % dotenv_file)


def handle_env(env_variables, local_env):
    if not env_variables:
        return

    for k, v in env_variables.items():
        if local_env:
            local_env[k] = os.path.expandvars(v)
            # print("local: %s = %s" % (k, local_env[k]))
        else:
            os.environ[k] = os.path.expandvars(v)
            # print("global: %s = %s" % (k, os.environ[k]))


def get_platform_working_dir(platform_id):
    from pathlib import Path
    workspace = Path(os.environ.get('FLUTTER_WORKSPACE'))
    cwd = workspace.joinpath('.config', 'flutter_workspace', platform_id)
    os.environ["PLATFORM_ID_DIR_RELATIVE"] = '.' + platform_id
    os.environ["PLATFORM_ID_DIR"] = str(cwd)
    print("Working Directory: %s" % cwd)
    make_sure_path_exists(cwd)
    return cwd


def create_platform_config_file(obj, cwd):
    if obj is None:
        return

    default_config_filepath = cwd.joinpath('default_config.json')
    with open(default_config_filepath, 'w+') as f:
        json.dump(obj, f, indent=2)


def is_host_type_supported(host_types):
    """Return true if host type is contained in host_types variable, false otherwise"""
    host_type = get_host_type()

    if host_type == 'linux':
        host_type = get_freedesktop_os_release_id()

    if host_type not in host_types:
        return False
    return True


def setup_platform(platform_, git_token, cookie_file, plex):
    """ Sets up platform """

    if platform_['id'] in plex:
        print_banner("PLEX - %s" % platform_['id'])
        return

    # if platform_['type'] == 'docker':
    runtime = platform_['runtime']

    # skip if architecture not supported
    host_machine_arch = get_host_machine_arch()
    if host_machine_arch not in platform_['supported_archs']:
        print_banner("\"%s\" not supported on this machine" % platform_['id'])
        return

    # skip if distro not supported
    if not is_host_type_supported(platform_['supported_host_types']):
        print_banner("\"%s\" not supported on this host type" %
                     platform_['id'])
        return

    print_banner("Setting up Platform %s - %s" %
                 (platform_['id'], host_machine_arch))

    cwd = get_platform_working_dir(platform_['id'])

    subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)

    handle_dotenv(platform_.get('dotenv'))
    handle_env(platform_.get('env'), None)
    create_platform_config_file(runtime.get('config'), cwd)
    subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)
    handle_artifacts_obj(runtime.get('artifacts'),
                         host_machine_arch, cwd, git_token, cookie_file)
    subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)
    handle_pre_requisites(runtime.get('pre-requisites'), cwd)
    subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)
    handle_docker_obj(runtime.get('docker'), host_machine_arch, cwd)
    subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)
    handle_conditionals(runtime.get('conditionals'), cwd)
    subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)
    handle_qemu_obj(runtime.get('qemu'), cwd, platform_[
        'id'], platform_['flutter_runtime'])
    subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)
    handle_commands_obj(runtime.get('post_cmds'), cwd)

    handle_custom_devices(platform_)


def setup_platforms(platforms, git_token, cookie_file, plex):
    """ Sets up each occurring platform defined """

    if plex:
        plex = plex.split(" ")

    for platform_ in platforms:
        setup_platform(platform_, git_token, cookie_file, plex)

        # reset sudo timeout
        subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)

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
        sys.exit("[get_github_artifact_list_json] GitHub Message: %s" %
                 data.get('message'))

    return {}


def get_github_workflow_runs(token, owner, repo, workflow):
    """ Gets workflow run list """

    url = "https://api.github.com/repos/%s/%s/actions/workflows/%s/runs" % (
        owner, repo, workflow)

    data = get_github_json(token, url)

    if 'workflow_runs' in data:
        return data.get('workflow_runs')

    if 'message' in data:
        sys.exit("[get_github_workflow_runs] GitHub Message: %s" %
                 data.get('message'))

    return {}


def get_github_workflow_artifacts(token, owner, repo, id_):
    """ Get Workflow Artifact List """

    url = "https://api.github.com/repos/%s/%s/actions/runs/%s/artifacts" % (
        owner, repo, id_)

    data = get_github_json(token, url)

    if 'artifacts' in data:
        return data.get('artifacts')

    if 'message' in data:
        sys.exit("[get_github_workflow_artifacts] GitHub Message: %s" %
                 data.get('message'))

    return {}


def get_workspace_tmp_folder() -> str:
    """ Gets tmp folder path located in workspace"""
    workspace = os.getenv("FLUTTER_WORKSPACE")
    tmp_folder = os.path.join(workspace, '.config', 'flutter_workspace', 'tmp')
    make_sure_path_exists(tmp_folder)
    return tmp_folder


def get_github_artifact(token: str, url: str, filename: str) -> str:
    """ Gets artifact via GitHub URL"""

    tmp_file = "%s/%s" % (get_workspace_tmp_folder(), filename)

    headers = ['Authorization: token %s' % token]
    if fetch_https_binary_file(url, tmp_file, True, headers, None, False):
        return tmp_file

    return ''


def ubuntu_is_pkg_installed(package: str) -> bool:
    """Ubuntu - checks if package is installed"""

    cmd = ['dpkg-query', '-W',
           '--showformat=\"${Status}\n\"', package, '|grep \"install ok installed\"']

    result = get_process_stdout(cmd).strip('\'').rstrip()

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
    ps = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = ps.communicate()[0]
    if len(output):
        return True
    return False


def get_mac_brew_path() -> str:
    """ Read which brew """
    result = subprocess.run(['which', 'brew'], stdout=subprocess.PIPE)
    return result.stdout.decode('utf-8').rstrip()


def get_mac_openssl_prefix() -> str:
    """ Read brew openssl prefix variable """
    if platform.machine() == 'arm64':
        return subprocess.check_output(
            ['arch', '-arm64', 'brew', '--prefix', 'openssl@3']).decode('utf-8').rstrip()
    else:
        return subprocess.check_output(['brew', '--prefix', 'openssl@3']).decode('utf-8').rstrip()


def mac_brew_reinstall_package(pkg):
    """ Re-installs brew package """
    if platform.machine() == 'arm64':
        subprocess.run(['arch', '-arm64', 'brew', 'reinstall', pkg])
    else:
        subprocess.run(['brew', 'reinstall', pkg])


def mac_pip3_install(pkg):
    """ Install pip3 on mac """
    if platform.machine() == 'arm64':
        cmd = 'arch -arm64 pip3 install %s' % pkg
    else:
        cmd = 'pip3 install %s' % pkg
    p = subprocess.Popen(cmd, universal_newlines=True, shell=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = p.stdout.read()
    p.wait()
    print(text)


def mac_is_cocoapods_installed():
    cmd = ['gem', 'list', '|', 'grep', 'cocoapods ']

    result = get_process_stdout(cmd).strip('\'').strip('\n')

    if 'cocoapods ' in result:
        print("Package cocoapods Found")
        return True
    else:
        print("Package cocoapods Not Found")
        return False


def mac_install_cocoapods_if_not_installed():
    if not mac_is_cocoapods_installed():
        subprocess.check_output(
            ['sudo', 'gem', '-y', 'install', 'activesupport', '-v', '6.1.7.3'])
        subprocess.check_output(['sudo', 'gem', '-y', 'install', 'cocoapods'])
        subprocess.run(
            ['sudo', 'gem', 'uninstall', 'ffi', '&&', 'sudo', 'gem', 'install', 'ffi', '--', '--enable-libffi-alloc'])


def install_minimum_runtime_deps():
    """Install minimum runtime deps to run this script"""
    host_type = get_host_type()

    if host_type == "linux":

        os_release_id = get_freedesktop_os_release_id()

        if os_release_id == 'ubuntu':
            cmd = ['sudo', 'apt', 'update', '-y']
            subprocess.check_output(cmd)
            packages = 'git git-lfs curl libcurl4-openssl-dev libssl-dev libgtk-3-dev ' \
                       'python3-dotenv python3-pycurl python3-pip'.split(' ')
            for package in packages:
                ubuntu_install_pkg_if_not_installed(package)

        elif os_release_id == 'fedora':
            cmd = ['sudo', 'dnf', '-y', 'update']
            subprocess.check_output(cmd)
            packages = 'dnf-plugins-core git git-lfs curl libcurl-devel openssl-devel ' \
                       'gtk3-devel python3-dotenv python3-pycurl python3-pip'.split(' ')
            for package in packages:
                fedora_install_pkg_if_not_installed(package)

    elif host_type == "darwin":
        brew_path = get_mac_brew_path()
        if brew_path == '':
            sys.exit(
                "brew is required for this script.  Please install.  https://brew.sh")

        mac_brew_reinstall_package('openssl@3')

        mac_pip3_install(
            '--install-option="--with-openssl" --install-option="--openssl-dir=%s" pycurl' % (get_mac_openssl_prefix()))

        mac_install_cocoapods_if_not_installed()


def is_repo(path):
    return os.path.exists(os.path.join(path, ".git"))


def get_random_mac() -> str:
    import random

    mac = [0x00, 0x16, 0x3e,
           random.randint(0x00, 0x7f),
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff)]

    return ':'.join(map(lambda x: "%02x" % x, mac))


env_prefix = '''#!/usr/bin/env bash -l

pushd . > '/dev/null'
SCRIPT_PATH=\"${BASH_SOURCE[0]:-$0}\"

while [ -h \"$SCRIPT_PATH\" ]
do
    cd \"$( dirname -- \"$SCRIPT_PATH\"; )\"
    SCRIPT_PATH=\"$( readlink -f -- \"$SCRIPT_PATH\"; )\"
done
cd \"$( dirname -- \"$SCRIPT_PATH\"; )\" > '/dev/null'

SCRIPT_PATH=\"$( pwd; )\"
popd  > '/dev/null'
echo SCRIPT_PATH=$SCRIPT_PATH

export FLUTTER_WORKSPACE=$SCRIPT_PATH
export PATH=$FLUTTER_WORKSPACE/flutter/bin:$PATH
export PUB_CACHE=$FLUTTER_WORKSPACE/.config/flutter_workspace/pub_cache
export XDG_CONFIG_HOME=$FLUTTER_WORKSPACE/.config/flutter

echo \"********************************************\"
echo \"* Setting FLUTTER_WORKSPACE to:\"
echo \"* ${FLUTTER_WORKSPACE}\"
echo \"********************************************\"

flutter doctor -v
flutter custom-devices list
'''


def write_env_script_header(workspace):
    """ Create environmental variable bash script """
    environment_script = os.path.join(workspace, 'setup_env.sh')

    with open(environment_script, 'w+') as script:
        script.write(env_prefix)


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


def get_linux_release_file():
    """Returns dictionary of releases_linux.json"""

    cwd = get_platform_working_dir('flutter-engine')

    filename = 'releases_linux.json'
    url = 'https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json'

    download_https_file(cwd, url, filename, None, None, None, None, None)

    return os.path.join(cwd, filename)


def get_version_files(cwd):
    """Get Dart and Engine Version files"""
    import concurrent.futures

    if cwd is None:
        cwd = get_platform_working_dir('flutter-engine')
    else:
        make_sure_path_exists(cwd)

    release_linux = get_linux_release_file()

    res = {}
    with open(release_linux, 'r') as f:
        for release in json.load(f).get('releases', []):
            if 'dart_sdk_version' in release:
                res[release['version']] = release['dart_sdk_version']

    dest_file = os.path.join(cwd, 'dart-revision.json')
    print_banner("Writing %s" % dest_file)
    with open(dest_file, 'w+') as o:
        json.dump(res, o, sort_keys=True, indent=2)

    print_banner('Fetching Engine revisions')
    engine_revs = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        with open(release_linux, 'r') as f:
            for release in json.load(f).get('releases', []):
                version_ = release['version']
                hash_ = release['hash']
                futures.append(executor.submit(get_engine_commit, version_, hash_))
                subprocess.check_call(
                    ['sudo', '-v'], stdout=subprocess.DEVNULL)

            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                engine_revs[res[0]] = res[1]
                subprocess.check_call(
                    ['sudo', '-v'], stdout=subprocess.DEVNULL)

    dest_file = os.path.join(cwd, 'engine-revision.json')
    print_banner("Writing %s" % dest_file)
    with open(dest_file, 'w+') as o:
        json.dump(engine_revs, o, sort_keys=True, indent=2)

    print_banner("Done")


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
        make_sure_path_exists(vscode_folder)
        with open(launch_file, 'w+') as f:
            json.dump(launch, f, indent=4)


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
            print(f"Attempt {i+1} failed: {e}")
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


def flash_mask_rom(platform_id: str, _id: str, platforms: dict):
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


def check_python_version():
    if sys.version_info[1] < 7:
        sys.exit('Python >= 3.7 required.  This machine is running 3.%s' %
                 sys.version_info[1])


if __name__ == "__main__":
    main()
