#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: (C) 2020-2024 Joel Winarske
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Script to create Yocto recipes from a given path.

import os
import signal
import sys

from fw_common import handle_ctrl_c
from fw_common import make_sure_path_exists
from fw_common import print_banner
from fw_common import check_python_version


def get_file_md5(file_name):
    import hashlib
    with open(file_name, 'rb') as f:
        data = f.read()
        md5_returned = hashlib.md5(data).hexdigest()
        return md5_returned


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--path', default='', type=str, help='Path to enumerate pubspec.yaml')
    parser.add_argument('--license', default='', type=str, help='License file relative to path value')
    parser.add_argument('--license_type', default='CLOSED', type=str, help='License type')
    parser.add_argument('--author', default='', type=str, help='value to assign to AUTHOR')
    parser.add_argument('--out', default='.', type=str, help='Output path to create the Yocto recipes in')
    args = parser.parse_args()

    if args.path == '':
        sys.exit("Must specify value for --path")

    if args.out == '':
        sys.exit("Must specify value for --out")

    #
    # Control+C handler
    #
    signal.signal(signal.SIGINT, handle_ctrl_c)

    #
    # Create yocto recipes from folder
    #
    if args.path:
        if not os.path.isdir(args.path):
            raise Exception(f'--path {args.path} is not a directory')

        # Check license file if specified
        license_md5 = ''
        if args.license:
            license_path = args.path + '/' + args.license
            if not os.path.isfile(license_path):
                raise Exception('--license {license_path} is not present')

            if args.license_type != 'CLOSED':
                license_md5 = get_file_md5(license_path)

        create_yocto_recipes(args.path,
                             args.license,
                             args.license_type,
                             license_md5,
                             args.author,
                             [],
                             args.out, args.out)
        return


def get_process_stdout(cmd, directory):
    import subprocess

    process = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, universal_newlines=True, cwd=directory)
    ret = ""
    for line in process.stdout:
        ret += str(line)
    process.wait()
    return ret.strip()


def get_git_branch(directory) -> str:
    """Get branch name"""
    branch = get_process_stdout('git symbolic-ref --short HEAD', directory)
    branch_lines = branch.split('\n')
    return branch_lines[0]


def get_repo_vars(directory):
    """Gets variables associated with repository"""

    if not os.path.isdir(directory):
        print_banner(f'ERROR: {directory} is not valid')
        raise Exception(f'{directory} is not valid')

    git_path = directory + '.git'
    if not os.path.isdir(git_path):
        print_banner(f'ERROR: {directory} is not a git repository')
        raise Exception(f'{directory} is not a git repository')

    remote_verbose = get_process_stdout('git remote -v', directory)
    remote_verbose = remote_verbose.split(' ')[0]
    remote_lines = remote_verbose.split('\n')
    remote_tokens = remote_lines[0]
    remote_lines = remote_tokens.split('\t')
    remote_lines[1] = remote_lines[1].replace('git@', 'https')
    repo = remote_lines[1].rsplit(sep='/', maxsplit=2)

    org = repo[-2].lower()
    repo = repo[-1].lower()
    unit = repo.split('.')

    submodules = False
    if os.path.isfile(directory + '/.gitmodules'):
        submodules = True

    lfs = False
    if os.path.isfile(directory + '/.gitattributes'):
        lfs = True

    branch = get_git_branch(directory)

    commit = get_process_stdout('git rev-parse --verify HEAD', directory)

    url_raw = get_process_stdout('git config --get remote.origin.url', directory)
    url = url_raw.split('//')

    value = ''
    if len(url) > 1:
        value = url[1]
    else:
        url = url_raw.split('@')
        if len(url) > 1:
            value = url[1]
        else:
            print('delimiter not handled')

    return org, unit[0], submodules, value, lfs, branch, commit


def get_yaml_obj(filepath: str):
    """ Returns python object of yaml file """
    import yaml

    if not os.path.exists(filepath):
        sys.exit(f'Failed loading {filepath}')

    with open(filepath, "r") as stream_:
        try:
            data_loaded = yaml.full_load(stream_)

        except yaml.YAMLError as exc:
            print(f'Failed loading {exc} - {filepath}')
            return []

        return data_loaded


def dedupe_adjacent(iterable):
    prev = object()
    for item in iterable:
        if item != prev:
            prev = item
            yield item


def create_recipe(directory,
                  pubspec_yaml,
                  org, unit, submodules, url, lfs, branch, commit,
                  license_file, license_type, license_file_md5,
                  author,
                  exclude_list,
                  output_path) -> str:

    is_web = False
    # TODO detect web

    path_tokens = pubspec_yaml.split('/')

    if path_tokens[-1] != 'pubspec.yaml':
        print_banner(f'ERROR: invalid {pubspec_yaml}')
        return ''

    # get relative path
    directory_tokens = directory.split('/')
    # remove end null entry
    del directory_tokens[-1]
    
    # pubspec.yaml key/values
    yaml_obj = get_yaml_obj(pubspec_yaml)
    if len(yaml_obj) == 0:
        print(f'Invalid YAML: {pubspec_yaml}')
        return ''

    project_name = yaml_obj.get('name')
    project_description = yaml_obj.get('description')
    project_homepage = yaml_obj.get('repository')
    project_issue_tracker = yaml_obj.get('issue_tracker')
    project_version = yaml_obj.get('version')

    # copy list
    app_path = path_tokens
    for i in range(len(directory_tokens)):
        del app_path[0]
    flutter_application_path = '/'.join(app_path[:-1])

    lib_main_dart = os.path.join(directory, flutter_application_path, 'lib', 'main.dart')
    if not os.path.exists(lib_main_dart):
        print(f'Skipping: {flutter_application_path}')
        return ''

    # exclude filtering
    if exclude_list and flutter_application_path in exclude_list:
        print(f'Exclude: {flutter_application_path}')
        return ''

    #
    # generate recipe name
    #

    # check if org and unit have overlap
    org_tokens = org.split('-')
    unit_tokens = unit.split('-')
    if org_tokens[-1] == unit_tokens[0]:
        tmp_header = org_tokens + unit_tokens[-1:]
        header = '-'.join(tmp_header)
    else:
        header = f'{org}-{unit}'

    app_path = flutter_application_path.replace('/', '-')
    app_path = app_path.replace('_', '-')

    app_path_tokens = app_path.split('-')
    header_tokens = header.split('-')

    if header_tokens[-1] == app_path_tokens[0]:
        tmp_app_path = header_tokens + app_path_tokens[:-1]
        app_path = '-'.join(tmp_app_path)

    if app_path.startswith(header):
        recipe_name = app_path
    else:
        recipe_name = f'{header}-{app_path}'

    vals = dedupe_adjacent(recipe_name.split('-'))
    recipe_name = '-'.join(vals)
    if recipe_name.endswith('-'):
        recipe_name = recipe_name[:-1]

    if project_version is not None:
        version = project_version.split('+')
        filename = f'{output_path}/{recipe_name}_{version[0]}.bb'
    else:
        filename = f'{output_path}/{recipe_name}_git.bb'

    with open(filename, "w") as f:
        f.write('#\n')
        f.write('# Copyright (c) 2020-2024 Joel Winarske. All rights reserved.\n')
        f.write('#\n')
        f.write('\n')

        if project_name:
            project_name = project_name.strip()
        if project_description:
            project_description = project_description.strip()
        if author:
            author = author.strip()
        if project_homepage:
            project_homepage = project_homepage.strip()
        if project_issue_tracker:
            project_issue_tracker = project_issue_tracker.strip()

        f.write(f'SUMMARY = "{project_name}"\n')
        f.write(f'DESCRIPTION = "{project_description}"\n')
        f.write(f'AUTHOR = "{author}"\n')
        f.write(f'HOMEPAGE = "{project_homepage}"\n')
        f.write(f'BUGTRACKER = "{project_issue_tracker}"\n')

        f.write('SECTION = "graphics"\n')
        f.write('\n')

        f.write(f'LICENSE = "{license_type}"\n')
        if license_type != 'CLOSED':
            f.write(f'LIC_FILES_CHKSUM = "file://{license_file};md5={license_file_md5}"\n')

        f.write('\n')
        f.write(f'SRCREV = "{commit}"\n')

        if submodules:
            fetcher = 'gitsm'
        else:
            fetcher = 'git'
        if lfs:
            lfs_option = 'lfs=1'
        else:
            lfs_option = 'lfs=0'
        if branch:
            branch_option = f'branch={branch}'
        else:
            branch_option = f'nobranch=1'

        f.write(f'SRC_URI = "{fetcher}://{url};{lfs_option};{branch_option};protocol=https;destsuffix=git"\n')
        f.write('\n')
        f.write('S = "${WORKDIR}/git"\n')
        f.write('\n')

        # detect melos
        if os.path.isfile(directory + '/melos.yaml'):
            f.write('PUB_CACHE_EXTRA_ARCHIVE_PATH = "${WORKDIR}/pub_cache/bin"\n')
            f.write('PUB_CACHE_EXTRA_ARCHIVE_CMD = "flutter pub global activate melos; \\\n')
            f.write('    melos bootstrap"\n')
            f.write('\n')

        f.write(f'PUBSPEC_APPNAME = "{project_name}"\n')
        f.write(f'FLUTTER_APPLICATION_INSTALL_SUFFIX = "{recipe_name}"\n')

        f.write(f'FLUTTER_APPLICATION_PATH = "{flutter_application_path}"\n')
        f.write('\n')

        if is_web:
            f.write('inherit flutter-web\n')
        else:
            f.write('inherit flutter-app\n')

        return recipe_name


def create_package_group(org, unit, recipes, output_path):
    """Create package group file"""

    filename = f'{output_path}/packagegroup-flutter-{org}-{unit}.bb'
    filename = filename.replace('_', '-')

    with open(filename, "w") as f:
        f.write('#\n')
        f.write('# Copyright (c) 2020-2024 Joel Winarske. All rights reserved.\n')
        f.write('#\n')
        f.write('\n')
        f.write(f'SUMMARY = "Package of Flutter {org} {unit} apps"\n')
        f.write('\n')
        f.write('PACKAGE_ARCH = "${MACHINE_ARCH}"\n')
        f.write('\n')
        f.write('inherit packagegroup\n')
        f.write('\n')
        f.write('RDEPENDS:${PN} += " \\\n')
        for i in range(len(recipes)):
            f.write(f'    {recipes[i]} \\\n')
        f.write('"\n')


def create_yocto_recipes(directory,
                         license_file,
                         license_type,
                         license_md5,
                         author,
                         exclude_list,
                         flutter_app_output_path,
                         packagegroups_output_path):
    """Create bb recipe for each pubspec.yaml file in path"""
    import glob

    print_banner("Creating Yocto Recipes")

    make_sure_path_exists(flutter_app_output_path)
    make_sure_path_exists(packagegroups_output_path)

    if not directory.endswith('/'):
        directory += '/'

    #
    # Get repo variables
    #
    org, unit, submodules, url, lfs, branch, commit = get_repo_vars(directory)

    #
    # Iterate all pubspec.yaml files
    #
    recipes = []
    for filename in glob.iglob(directory + '**/pubspec.yaml', recursive=True):
        recipe = create_recipe(directory, filename,
                               org, unit, submodules, url, lfs, branch, commit,
                               license_file, license_type, license_md5,
                               author,
                               exclude_list,
                               flutter_app_output_path
                               )
        if recipe != '':
            recipes.append(recipe)

    create_package_group(org, unit, recipes, packagegroups_output_path)

    print_banner("Creating Yocto Recipes done.")


if __name__ == "__main__":
    check_python_version()

    main()
