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

        create_yocto_recipes(args.path, args.license, args.license_type, license_md5, args.author, args.out)
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
        raise Exception(f'{directory} is not valid')

    git_path = directory + '.git'
    if not os.path.isdir(git_path):
        raise Exception(f'{directory} is not a git repository')

    remote_verbose = get_process_stdout('git remote -v', directory)
    remote_lines = remote_verbose.split('\n')
    remote_tokens = remote_lines[0]
    remote_lines = remote_tokens.split('\t')
    remote_lines[1] = remote_lines[1].replace('git@','https')
    remote_lines[1] = remote_lines[1].replace(':','/')
    repo = remote_lines[1].rsplit(sep='/', maxsplit=2)

    org = repo[-2]
    repo = repo[-1]
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
            sys.exit(f'Failed loading {exc} - {filepath}')

        return data_loaded


def create_recipe(pubspec_yaml,
                  org, unit, submodules, url, lfs, branch, commit,
                  license_file, license_type, license_file_md5,
                  author,
                  output_path):

    if '_ios' in pubspec_yaml or '_android' in pubspec_yaml or '_windows' in pubspec_yaml or '_macos' in pubspec_yaml or '_web' in pubspec_yaml:
        print(f'Skipping: {pubspec_yaml}')
        return

    path_tokens = pubspec_yaml.split('/')

    if path_tokens[-1] == 'pubspec.yaml':

        if unit != path_tokens[-3]:
            recipe_name = f'{org}-{unit}-{path_tokens[-3]}-{path_tokens[-2]}'
        else:
            recipe_name = f'{org}-{unit}-{path_tokens[-2]}'

        recipe_name = recipe_name.replace('_','-')

        obj = get_yaml_obj(pubspec_yaml)
        project_name = obj.get('name')
        project_description = obj.get('description')
        project_homepage = obj.get('repository')
        project_issue_tracker = obj.get('issue_tracker')
        project_version = obj.get('version')

        if project_version != None:
            version = project_version.split('+')
            filename = f'{output_path}/{recipe_name}_{version[0]}.bb'
        else:
            filename = f'{output_path}/{recipe_name}_git.bb'

        print(f'Recipe: {filename}')

        with open(filename, "w") as f:

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
            f.write(f'PUBSPEC_APPNAME = "{project_name}"\n')
            flutter_application_path = '/'.join(path_tokens[:-1])
            f.write(f'FLUTTER_APPLICATION_PATH = "{flutter_application_path}"\n')
            f.write('\n')
            # TODO detect if web or app. Use app for now
            f.write('inherit flutter-app\n')


def create_yocto_recipes(directory, license_file, license_type, license_md5, author, output_path):
    """Create bb recipe for each pubspec.yaml file in path"""
    import glob
    from subprocess import Popen, PIPE

    print_banner("Creating Yocto Recipes")

    make_sure_path_exists(output_path)

    #
    # Get repo variables
    #
    org, unit, submodules, url, lfs, branch, commit = get_repo_vars(directory)

    #
    # Iterate on all pubspec.yaml files
    #
    for filename in glob.iglob(directory + '**/pubspec.yaml', recursive=True):
        create_recipe(filename, org, unit, submodules, url, lfs, branch, commit, license_file, license_type, license_md5, author, output_path)

    print_banner("Done.")


if __name__ == "__main__":
    check_python_version()

    main()
