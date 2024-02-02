#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: (C) 2020-2023 Joel Winarske
#
# SPDX-License-Identifier: Apache-2.0
#
#
# Script to roll meta-flutter layer

import os
import signal
import subprocess
import sys

from create_recipes import create_yocto_recipes
from create_recipes import get_file_md5
from fw_common import check_python_version
from fw_common import handle_ctrl_c
from fw_common import make_sure_path_exists
from fw_common import print_banner
from fw_common import test_internet_connection
from version_files import get_version_files


def get_flutter_apps(filename) -> dict:
    import json
    filepath = os.path.join(os.getcwd(), filename)
    with open(filepath, 'r') as f:
        try:
            return json.load(f)
        except json.decoder.JSONDecodeError:
            print("Invalid JSON in %s" % f)
            exit(1)


def clear_folder(dir_):
    """ Clears folder specified """
    import shutil
    if os.path.exists(dir_):
        shutil.rmtree(dir_)


def get_repo(base_folder, uri, branch, rev, license_file, license_type, author, output_path):
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

    git_lfs_file = os.path.join(base_folder, repo_name, '.gitattributes')
    if os.path.exists(git_lfs_file):
        cmd = ['git', 'lfs', 'fetch', '--all']
        subprocess.check_call(cmd, cwd=git_folder)

    repo_path = os.path.join(base_folder, repo_name)

    # Check license file
    license_md5 = ''
    if license_file:
        license_path = os.path.join(repo_path, license_file)
        if not os.path.isfile(license_path):
            print_banner(f'ERROR: {license_path} is not present')
            exit(1)

        if license_type != 'CLOSED':
            license_md5 = get_file_md5(license_path)

    create_yocto_recipes(repo_path,
                         license_file,
                         license_type,
                         license_md5,
                         author,
                         os.path.join(output_path, 'recipes-graphics', 'flutter-apps'),
                         os.path.join(output_path, 'recipes-platform', 'packagegroups'))


def get_workspace_repos(base_folder, repos, output_path):
    """ Clone GIT repos referenced in config repos dict to base_folder """
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for repo in repos:
            futures.append(executor.submit(get_repo, base_folder=base_folder,
                                           uri=repo.get('uri'),
                                           branch=repo.get('branch'),
                                           rev=repo.get('rev'),
                                           license_file=repo.get('license_file'),
                                           license_type=repo.get('license_type'),
                                           author=repo.get('author'),
                                           output_path=output_path
                                           ))

    print_banner("Repos Cloned")


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--path', default='', type=str, help='meta-flutter root path')
    parser.add_argument('--json', default='configs/flutter-apps.json', type=str, help='JSON file of flutter apps')
    args = parser.parse_args()

    #
    # Control+C handler
    #
    signal.signal(signal.SIGINT, handle_ctrl_c)

    if not os.path.exists(args.path):
        make_sure_path_exists(args.path)

    print_banner('Rolling meta-flutter')
    print_banner('Updating version files')

    include_path = os.path.join(args.path, 'conf', 'include')
    get_version_files(include_path)

    print_banner('Done updating version files')

    print_banner('Updating flutter apps recipes')
    flutter_apps = get_flutter_apps(args.json)

    repo_path = os.path.join(os.getcwd(), '.flutter-apps')
    make_sure_path_exists(repo_path)

    make_sure_path_exists(args.path)
    get_workspace_repos(repo_path, flutter_apps, args.path)

    clear_folder(repo_path)

    print_banner('Done')


if __name__ == "__main__":
    check_python_version()

    if not test_internet_connection():
        sys.exit("roll_meta_flutter.py requires an internet connection")

    main()
