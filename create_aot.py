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
from fw_common import run_command


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

    gen_snapshot = os.getenv('GEN_SNAPSHOT')
    if gen_snapshot is None:
        sys.exit('Set GEN_SNAPSHOT to location of executable gen_snapshot')

    cmd = f'{gen_snapshot} --version 2>&1 | cut -d\\" -f2'
    gen_snapshot_variant = run_command(cmd, app_path)
    if gen_snapshot_variant == 'linux_x64':
        sys.exit(f'{gen_snapshot} intended for host build, skipping!')

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

    flutter_sdk_root = os.getenv("LOCAL_ENGINE_HOST")
    if flutter_sdk_root is None:
        flutter_sdk_root = f'{flutter_sdk}/bin/cache/artifacts/engine/common'

    for runtime_mode in flutter_runtime_modes:

        print_banner(f'[{runtime_mode}] flutter build {flutter_build_args}: Starting')

        run_command('flutter clean', app_path)

        if runtime_mode == 'jit_release':
            cmd = f'flutter build {flutter_build_args} --local-engine'
        else:
            cmd = f'flutter build {flutter_build_args}'
        run_command(cmd, app_path)

        print_banner(f'[{runtime_mode}] flutter build {flutter_build_args}: Completed')

        if runtime_mode == 'release' or 'profile':

            print_banner(f'kernel_snapshot_{runtime_mode}: Starting')

            flutter_sdk_root_patched = f'{flutter_sdk_root}/flutter_patched_sdk/'
            flutter_app_vm_product = 'false'
            if runtime_mode == 'release':
                flutter_sdk_root_patched = f'{flutter_sdk_root}/flutter_patched_sdk_product/'
                if not os.path.exists(flutter_sdk_root_patched):
                    flutter_sdk_root_patched = f'{flutter_sdk_root}/flutter_patched_sdk/'
                flutter_app_vm_product = 'true'

            flutter_app_profile_flags = ''
            flutter_app_vm_profile = 'false'
            if runtime_mode == 'profile':
                flutter_app_profile_flags = '--track-widget-creation'
                flutter_app_vm_profile = 'true'

            flutter_release_and_profile_flags = ''
            if runtime_mode != 'debug':
                flutter_release_and_profile_flags = '--aot --tfa --target-os linux'

            flutter_app_debug_flags = ''
            flutter_app_debug_flags_extra = ''
            flutter_app_app_dill = f'--output-dill {app_path}/.dart_tool/flutter_build/*/app.dill'
            if runtime_mode == 'debug':
                flutter_app_debug_flags = '--enable-asserts'
                flutter_app_debug_flags += ' --track-widget-creation'
                flutter_app_debug_flags += ' --no-link-platform'
                flutter_app_debug_flags_extra = '--filesystem-scheme org-dartlang-root'
                flutter_app_debug_flags_extra += ' --incremental'
                flutter_app_debug_flags_extra += f' --initialize-from-dill {app_path}/.dart_tool/flutter_build/*/app.dill'

            flutter_source_flags = ''
            dart_plugin_registrant_file = f'{app_path}/.dart_tool/flutter_build/dart_plugin_registrant.dart'
            if os.path.exists(dart_plugin_registrant_file):
                # filter_linux_plugin_registrant(dart_plugin_registrant_file)
                flutter_source_flags = f'--source file://{dart_plugin_registrant_file}'
                flutter_source_flags += ' --source package:flutter/src/dart_plugin_registrant.dart'
                flutter_source_flags += f' -Dflutter.dart_plugin_registrant=file://{dart_plugin_registrant_file}'

            flutter_native_assets = ''
            if os.path.exists(f'{app_path}.dart_tool/flutter_build/*/native_assets.yaml'):
                flutter_native_assets = f'--native-assets {app_path}/.dart_tool/flutter_build/*/native_assets.yaml'

            app_aot_extra = os.getenv("APP_AOT_EXTRA")
            if app_aot_extra is None:
                app_aot_extra = ''

            cmd = f'{flutter_sdk}/bin/cache/dart-sdk/bin/dart \
                --disable-analytics \
                --disable-dart-dev \
                {flutter_sdk}/bin/cache/artifacts/engine/linux-x64/frontend_server.dart.snapshot \
                --sdk-root {flutter_sdk_root_patched} \
                --target=flutter \
                --no-print-incremental-dependencies \
                -Ddart.vm.profile={flutter_app_vm_profile} \
                -Ddart.vm.product={flutter_app_vm_product} \
                {app_aot_extra} \
                {flutter_app_debug_flags} \
                {flutter_app_profile_flags} \
                {flutter_release_and_profile_flags} \
                --packages {app_path}/.dart_tool/package_config.json \
                {flutter_app_app_dill} \
                --depfile {app_path}/.dart_tool/flutter_build/*/kernel_snapshot.d \
                {flutter_source_flags} \
                {flutter_app_debug_flags_extra} \
                {flutter_native_assets} \
                --verbosity=error \
                package:{pubspec_appname}/main.dart'

            run_command(cmd, app_path)

            print_banner(f'kernel_snapshot_{runtime_mode}: Complete')

            print_banner(f'aot_elf_{runtime_mode}: Started')

            #
            # Create app-aot-elf
            #
            app_gen_snapshot_flags = os.getenv("APP_GEN_SNAPSHOT_FLAGS")
            if app_gen_snapshot_flags is None:
                app_gen_snapshot_flags = ''
            app_gen_snapshot_flags += ' --strip'
            app_gen_snapshot_flags += ' --obfuscate'
            app_gen_snapshot_flags += ' --deterministic'

            print_banner(gen_snapshot_variant)

            gen_snapshot_kind_flags = ''
            app_gen_snapshot_aot_filename = os.getenv("APP_GEN_SNAPSHOT_AOT_FILENAME")
            if gen_snapshot_variant == 'linux_simarm64':
                gen_snapshot_kind_flags = '--snapshot_kind=app-aot-elf'
                if app_gen_snapshot_aot_filename is None:
                    app_gen_snapshot_aot_filename = f'libapp.so.{runtime_mode}'
                gen_snapshot_kind_flags += f' --elf={app_gen_snapshot_aot_filename}'

            if runtime_mode != 'debug':
                cmd = f'{gen_snapshot} \
                    {gen_snapshot_kind_flags} \
                    {app_gen_snapshot_flags} \
                    {app_path}/.dart_tool/flutter_build/*/app.dill'

                run_command(cmd, app_path)

    print_banner('Complete')
    sys.exit()


def check_python_version():
    if sys.version_info[1] < 7:
        sys.exit('Python >= 3.7 required.  This machine is running 3.%s' %
                 sys.version_info[1])


if __name__ == "__main__":
    check_python_version()
    main()
