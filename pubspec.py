#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: (C) 2020-2023 Joel Winarske
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Script to build custom Flutter AOT artifacts for Release and Profile runtime

import os
import sys
import yaml


class Pubspec:
    def __init__(self, filepath, platform):
        self.pub_cache = os.getenv("PUB_CACHE")
        if self.pub_cache == None:
            raise Exception ("Environmental variable PUB_CACHE is not set")

        self.root_path = os.path.abspath(filepath)
        self.platform = platform
        self.plugins = []

        self.parse_platform_plugins()


    def get_yaml(self, filepath: str):
        """ Returns python object of yaml file """

        if not os.path.exists(filepath):
            print(f'File does not exist: {filepath}')
            return None

        with open(filepath, "r") as stream_:
            try:
                data = yaml.full_load(stream_)

            except yaml.YAMLError as exc:
                raise Exception(f'Failed loading {exc} - {filepath}')
            
            return data


    def write_to_file(self, obj: object, filepath: str):
        """ Writes YAML object to file """

        with open(filepath, 'w') as file:
            yaml.dump(obj, file)


    def get_plugin_default_package(self, filepath: str):
        pubspec = os.path.join(filepath, 'pubspec.yaml')
        obj = self.get_yaml(pubspec)
        if type(obj) is dict and 'flutter' in obj:
            if type(obj['flutter']) is dict and 'plugin' in obj['flutter']:
                if type(obj['flutter']['plugin']) is dict and 'platforms' in obj['flutter']['plugin']:
                    if (type(obj['flutter']['plugin']['platforms']) is dict and
                            self.platform in obj['flutter']['plugin']['platforms']):
                        if 'default_package' in obj['flutter']['plugin']['platforms'][self.platform]:
                            default_package = obj['flutter']['plugin']['platforms'][self.platform]['default_package']
                            return default_package
        return None


    def get_dart_plugin_class(self, filepath: str):
        pubspec = os.path.join(filepath, 'pubspec.yaml')
        obj = self.get_yaml(pubspec)
        if type(obj) is dict and 'flutter' in obj:
            if type(obj['flutter']) is dict and 'plugin' in obj['flutter']:
                if type(obj['flutter']['plugin']) is dict and 'platforms' in obj['flutter']['plugin']:
                    if (type(obj['flutter']['plugin']['platforms']) is dict and
                            self.platform in obj['flutter']['plugin']['platforms']):
                        if 'dartPluginClass' in obj['flutter']['plugin']['platforms'][self.platform]:
                            dart_plugin_class = obj['flutter']['plugin']['platforms'][self.platform]['dartPluginClass']
                            return dart_plugin_class
        return None


    def parse_platform_plugins(self):
        pubspec_lock_file = os.path.join(self.root_path,'pubspec.lock')
        lock = self.get_yaml(pubspec_lock_file)
        for package in lock['packages']:
            source = lock['packages'][package]['source']
            version = lock['packages'][package]['version']
            package_folder = os.path.join(self.pub_cache, source, 'pub.dev', f'{package}-{version}')
            if os.path.exists(package_folder):
                default_package = self.get_plugin_default_package(package_folder)
                if default_package:
                    source = lock['packages'][default_package]['source']
                    version = lock['packages'][default_package]['version']
                    default_package_path = os.path.join(self.pub_cache, source, 'pub.dev', f'{default_package }-{version}')
                    if os.path.exists(default_package_path):
                        dart_plugin_class = self.get_dart_plugin_class(default_package_path)
                        if dart_plugin_class:
                            self.plugins.append([dart_plugin_class, default_package, default_package_path])

    def print_plugins(self):
        for plugin in self.plugins:
            print(f'dart_plugin_class: {plugin[0]}')
            print(f'package: {plugin[1]}')
            print(f'package_path: {plugin[2]}')


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-path', default='', type=str, help='return pubspec.yaml info')
    parser.add_argument('--platform', default='linux', type=str, help='specify plugin platform type')
    args = parser.parse_args()

    #
    # pubspec parsing
    #
    if args.app_path != '':
        pubspec = Pubspec(args.app_path, args.platform)
        pubspec.print_plugins()


def check_python_version():
    if sys.version_info[1] < 7:
        sys.exit('Python >= 3.7 required.  This machine is running 3.%s' %
                 sys.version_info[1])


if __name__ == "__main__":
    main()
