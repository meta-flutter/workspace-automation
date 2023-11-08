#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: (C) 2020-2023 Joel Winarske
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Script to build custom Flutter AOT artifacts for Release and Profile runtime

import os
import signal
import sys

from fw_common import handle_ctrl_c
from fw_common import print_banner


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-path', default='', type=str, help='Specify Application path')
    args = parser.parse_args()

    if args.app_path == '':
        sys.exit("Must specify value for --app-path")

    #
    # Control+C handler
    #
    signal.signal(signal.SIGINT, handle_ctrl_c)

    create_platform_aot(args.app_path)


def filter_linux_plugin_registrant(dart_file: str):
    """ Removes unused items from the dart plugin registrant file """

    if not os.path.exists(dart_file):
        return

    with open(dart_file, "r") as f:
        lines = f.readlines()

    discard = False
    with open(dart_file, "w") as f:
        for line in lines:
            if line.find('import') != -1 and line.find('_android') != -1:
                continue
            elif line.find('import') != -1 and line.find('_ios') != -1:
                continue
            elif line.find('import') != -1 and line.find('_windows') != -1:
                continue
            elif line.find('import') != -1 and line.find('_macos') != -1:
                continue
            elif line.find('(Platform.isAndroid)') != -1:
                discard = True
                continue
            elif line.find('(Platform.isIOS)') != -1:
                discard = True
                continue
            elif line.find('(Platform.isMacOS)') != -1:
                discard = True
                continue
            elif line.find('(Platform.isWindows)') != -1:
                discard = True
                continue
            elif line.find('(Platform.isLinux)') != -1:
                f.write('    if (Platform.isLinux) {\n')
                discard = False
                continue
            elif line == '    }\n':
                f.write(line)
                discard = False
                continue
            elif not discard:
                f.write(line)
                continue
            else:
                continue
        f.write('    }\n  }\n}\n')


def run_command(cmd, cwd):
    """ Run Command in specified working directory """
    import re
    import subprocess

    # replace all consecutive whitespace characters (tabs, newlines etc.) with a single space
    cmd = re.sub('\s{2,}', ' ', cmd)

    print('Running [%s] in %s' % (cmd, cwd))
    (retval, output) = subprocess.getstatusoutput(f'cd {cwd} && {cmd}')
    if retval:
        sys.exit("failed %s (cmd was %s)%s" % (retval, cmd, ":\n%s" % output if output else ""))


def get_yaml_obj(filepath: str):
    """ Returns python object of yaml file """
    import yaml

    if not os.path.exists(filepath):
        sys.exit(f'Failed loading {filepath}')

    with open(filepath, "r") as stream_:
        try:
            data_loaded = yaml.full_load(stream_)

        except yaml.YAMLError as exc:
            sys.exit(f'Failed loading {exc} - {filepath}')

        return data_loaded


def create_platform_aot(app_path: str):
    """ Creates a platform AOT for Release and Profile """
    print_banner(f'Creating AOT Release and Profile in {app_path}')

    """ enforce absolute path usage """
    app_path = os.path.abspath(app_path)

    pub_cache = os.getenv("PUB_CACHE")
    if pub_cache is None:
        sys.exit("Environmental variable PUB_CACHE is not set")
    print(f'PUB_CACHE={pub_cache}')

    pubspec_yaml = os.path.join(app_path, 'pubspec.yaml')
    obj = get_yaml_obj(pubspec_yaml)
    pubspec_appname = obj.get('name')

    flutter_workspace = os.getenv("FLUTTER_WORKSPACE")
    flutter_sdk = os.path.join(flutter_workspace, 'flutter')

    cmd = os.getenv('FLUTTER_PREBUILD_CMD')
    if cmd is not None:
        run_command(cmd, app_path)

    flutter_runtime_modes = ['release', 'profile']

    flutter_build_args = os.getenv('FLUTTER_BUILD_ARGS')
    if flutter_build_args is None:
        flutter_build_args = 'bundle'

    for runtime_mode in flutter_runtime_modes:

        print(f'[{runtime_mode}] flutter build {flutter_build_args}: Starting')

        run_command('flutter clean', app_path)

        if runtime_mode == 'jit_release':
            cmd = f'flutter build {flutter_build_args} --local-engine'
        else:
            cmd = f'flutter build {flutter_build_args}'
        run_command(cmd, app_path)

        print(f'[{runtime_mode}] flutter build {flutter_build_args}: Completed')

        if runtime_mode == 'release' or 'profile':

            print(f'kernel_snapshot_{runtime_mode}: Starting')

            flutter_app_sdk_root = f'{flutter_sdk}/bin/cache/artifacts/engine/common/flutter_patched_sdk/'
            flutter_app_vm_product = "false"
            if runtime_mode == 'release':
                flutter_app_sdk_root = f'{flutter_sdk}/bin/cache/artifacts/engine/common/flutter_patched_sdk_product/'
                flutter_app_vm_product = "true"

            flutter_app_profile_flags = ''
            flutter_app_vm_profile = 'false'
            if runtime_mode == 'profile':
                flutter_app_profile_flags = '--track-widget-creation'
                flutter_app_vm_profile = 'true'

            flutter_app_debug_flags = ''
            flutter_app_app_dill = '--output-dill .dart_tool/flutter_build/*/app.dill'
            if runtime_mode == 'debug':
                flutter_app_debug_flags = '--enable-asserts'
                flutter_app_app_dill = '.dart_tool/flutter_build/*/app.dill'

            flutter_source_file = ''
            flutter_source_package = ''
            flutter_source_defines = ''
            dart_plugin_registrant_file = f'{app_path}/.dart_tool/flutter_build/dart_plugin_registrant.dart'
            if os.path.exists(dart_plugin_registrant_file):
                # filter_linux_plugin_registrant(dart_plugin_registrant_file)
                flutter_source_file = f'--source file://{dart_plugin_registrant_file}'
                flutter_source_package = '--source package:flutter/src/dart_plugin_registrant.dart'
                flutter_source_defines = f'-Dflutter.dart_plugin_registrant=file://{dart_plugin_registrant_file}'

            flutter_native_assets = ''
            if os.path.exists(f'{app_path}.dart_tool/flutter_build/*/native_assets.yaml'):
                flutter_native_assets = f'--native-assets {app_path}/.dart_tool/flutter_build/*/native_assets.yaml'

            app_aot_extra = os.getenv("APP_AOT_EXTRA")
            if app_aot_extra is None:
                app_aot_extra = ''

            cmd = f'{flutter_sdk}/bin/cache/dart-sdk/bin/dart \
                --disable-analytics \
                --disable-dart-dev {flutter_sdk}/bin/cache/artifacts/engine/linux-x64/frontend_server.dart.snapshot \
                --sdk-root {flutter_app_sdk_root} \
                --target=flutter \
                --no-print-incremental-dependencies \
                -Ddart.vm.profile={flutter_app_vm_profile} \
                -Ddart.vm.product={flutter_app_vm_product} \
                {app_aot_extra} \
                {flutter_app_debug_flags} \
                {flutter_app_profile_flags} \
                --aot \
                --tfa \
                --target-os linux \
                --packages {app_path}/.dart_tool/package_config.json \
                {flutter_app_app_dill} \
                --depfile {app_path}/.dart_tool/flutter_build/*/kernel_snapshot.d \
                {flutter_source_file} \
                {flutter_source_package} \
                {flutter_source_defines} \
                {flutter_native_assets} \
                --verbosity=error \
                package:{pubspec_appname}/main.dart'

            run_command(cmd, app_path)

            print(f'kernel_snapshot_{runtime_mode}: Complete')

            print(f'aot_elf_{runtime_mode}: Started')

            gen_snapshot = os.getenv('GEN_SNAPSHOT')
            if gen_snapshot is None:
                sys.exit('Set GEN_SNAPSHOT to location of executable gen_snapshot')

            #
            # Create libapp.so
            #
            app_gen_snapshot_flags = os.getenv("APP_GEN_SNAPSHOT_FLAGS")
            if app_gen_snapshot_flags is None:
                app_gen_snapshot_flags = ''

            cmd = f'{gen_snapshot} \
                --deterministic \
                --snapshot_kind=app-aot-elf \
                --elf=libapp.so.{runtime_mode} \
                --strip \
                --obfuscate \
                {app_gen_snapshot_flags} \
                .dart_tool/flutter_build/*/app.dill'

            run_command(cmd, app_path)

    print_banner('Complete')
    sys.exit()


def check_python_version():
    if sys.version_info[1] < 7:
        sys.exit('Python >= 3.7 required.  This machine is running 3.%s' %
                 sys.version_info[1])


if __name__ == "__main__":
    main()
