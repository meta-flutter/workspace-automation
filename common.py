#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: (C) 2020-2025 workspace-automation contributors
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import platform
import subprocess
import sys

from platform import system
from sys import stderr as stream

# use kiB's
kb = 1024


def get_host_machine_arch():
    os.environ['HOST_ARCH'] = platform.machine()
    return platform.machine()


def get_flutter_arch():
    host_arch = get_host_machine_arch()
    if host_arch == 'x86_64':
        os.environ['HOST_ARCH_GOOGLE'] = 'x64'
        return 'x64'
    elif host_arch == 'AMD64':
        os.environ['HOST_ARCH_GOOGLE'] = 'x64'
        return 'x64'
    elif host_arch == 'arm64':
        os.environ['HOST_ARCH_GOOGLE'] = 'arm64'
        return 'arm64'
    elif host_arch == 'ARM64':
        os.environ['HOST_ARCH_GOOGLE'] = 'arm64'
        return 'arm64'
    elif host_arch == 'aarch64':
        os.environ['HOST_ARCH_GOOGLE'] = 'aarch64'
        return 'arm64'
    else:
        print_banner(f'Unknown host arch: {host_arch}')
        sys.exit(1)


def check_python_version():
    if sys.version_info[1] < 7:
        sys.exit('Python >= 3.7 required.  This machine is running 3.%s' %
                 sys.version_info[1])


def print_banner(text):
    print('*' * (len(text) + 6))
    print("** %s **" % text)
    print('*' * (len(text) + 6))


def handle_ctrl_c(_signal, _frame):
    sys.exit("Ctl+C - Closing")


def run_command(cmd: str, cwd: str) -> str:
    """ Run Command in specified working directory """
    import re
    import shlex
    import subprocess

    # replace all consecutive whitespace characters (tabs, newlines, etc.) with a single space
    cmd = re.sub('\\s{2,}', ' ', cmd)

    print('Running [%s] in %s' % (cmd, cwd))
    cmd_arr = shlex.split(cmd)
    result = subprocess.run(cmd_arr, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        output = result.stdout + result.stderr
        sys.exit("failed %s (cmd was %s)%s" % (result.returncode, cmd, ":\n%s" % output.rstrip() if output.rstrip() else ""))

    output = result.stdout + result.stderr
    print(output.rstrip())
    return output.rstrip()


def get_md5sum(file: str) -> str:
    """Return file md5sum"""
    import hashlib

    if not os.path.exists(file):
        return ''

    md5_hash = hashlib.md5()
    with open(file, "rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)

    return md5_hash.hexdigest()


def get_sha1sum(file: str) -> str:
    """Return file sha1 sum"""
    import hashlib

    if not os.path.exists(file):
        return ''

    sha1_hash = hashlib.sha1()
    with open(file, "rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha1_hash.update(byte_block)

    return sha1_hash.hexdigest()


def get_sha256sum(file: str):
    """Return file sha256sum"""
    import hashlib

    if not os.path.exists(file):
        return ''

    sha256_hash = hashlib.sha256()
    with open(file, "rb") as f:
        # Read and update hash in chunks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)

    return sha256_hash.hexdigest()


def download_https_file(cwd, url, file, cookie_file, netrc, md5, sha1, sha256, redirect=False, connect_timeout=None):
    download_filepath = str(os.path.join(cwd, file))

    sha256_file = str(os.path.join(cwd, file + '.sha256'))
    if compare_sha256(download_filepath, sha256_file):
        print("%s exists, skipping download" % download_filepath)
        return True

    if os.path.exists(download_filepath):
        if md5:
            # don't download if md5 is good
            if md5 == get_md5sum(download_filepath):
                print("** Using %s" % download_filepath)
                return True
            else:
                os.remove(download_filepath)
        elif sha1:
            # don't download if sha1 is good
            if sha1 == get_sha1sum(download_filepath):
                print("** Using %s" % download_filepath)
                return True
            else:
                os.remove(download_filepath)
        elif sha256:
            # don't download if sha256 is good
            if sha256 == get_sha256sum(download_filepath):
                print("** Using %s" % download_filepath)
                return True
            else:
                os.remove(download_filepath)

    print("** Downloading %s via %s" % (file, url))
    res = fetch_https_binary_file(
        url, download_filepath, redirect, None, cookie_file, netrc, connect_timeout)
    if not res:
        os.remove(download_filepath)
        print_banner("Failed to download %s" % file)
        return False

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
                         (download_filepath, sha1, expected_sha1))
        elif sha256:
            expected_sha256 = get_sha256sum(download_filepath)
            if sha256 != expected_sha256:
                sys.exit('Download artifact %s sha256: %s does not match expected: %s' %
                         (download_filepath, sha256, expected_sha256))

    write_sha256_file(cwd, file)
    return True


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


_fetch_https_progress_last_time = 0.0
_fetch_https_progress_last_values = (None, None)


def fetch_https_progress(download_t, download_d, _upload_t, _upload_d):
    """callback function for pycurl transfer info function"""
    import time
    global _fetch_https_progress_last_time, _fetch_https_progress_last_values

    if os.environ.get('CI') == 'true':
        # Skips printing progress more than once a second or if values haven't changed to avoid log spew.
        now = time.monotonic()
        current_values = (download_t, download_d)
        if current_values == _fetch_https_progress_last_values or (now - _fetch_https_progress_last_time) < 1.0:
            return

        _fetch_https_progress_last_time = now
        _fetch_https_progress_last_values = current_values
    
    stream.write('Progress: {}/{} kiB ({}%)\r'.format(str(int(download_d / kb)), str(int(download_t / kb)),
                                                      str(int(download_d / download_t * 100) if download_t > 0 else 0)))
    stream.flush()


def _fetch_https_binary_file_urllib(url, filename, redirect, headers, cookie_file, netrc, connect_timeout) -> bool:
    """Fallback HTTPS file download using urllib when pycurl is unavailable"""
    import time
    import urllib.request
    import ssl
    import http.cookiejar

    retries_left = 3
    delay_between_retries = 5  # seconds

    try:
        import certifi
        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ssl_context = ssl.create_default_context()

    while retries_left > 0:
        try:
            req = urllib.request.Request(url)

            if headers:
                for header in headers:
                    key, value = header.split(':', 1)
                    req.add_header(key.strip(), value.strip())

            opener_handlers = [urllib.request.HTTPSHandler(context=ssl_context)]

            if not redirect:
                class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, headers, newurl):
                        return None
                opener_handlers.append(NoRedirectHandler())

            if cookie_file:
                cookie_file = os.path.expandvars(cookie_file)
                print("Using cookie file: %s" % cookie_file)
                cj = http.cookiejar.MozillaCookieJar(cookie_file)
                cj.load()
                opener_handlers.append(urllib.request.HTTPCookieProcessor(cj))

            opener = urllib.request.build_opener(*opener_handlers)

            open_kwargs = {}
            if connect_timeout is not None:
                open_kwargs['timeout'] = connect_timeout

            with opener.open(req, **open_kwargs) as response:
                status = response.getcode()

                if not redirect and status == 302:
                    print_banner("Download Status: %d" % status)
                    return False

                with open(filename, 'wb') as f:
                    total = response.headers.get('Content-Length')
                    downloaded = 0
                    block_size = 8192
                    while True:
                        chunk = response.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            total_kb = int(total) // kb
                            done_kb = downloaded // kb
                            pct = int(downloaded / int(total) * 100)
                            stream.write('Progress: {}/{} kiB ({}%)\r'.format(done_kb, total_kb, pct))
                            stream.flush()

                if status != 200:
                    print_banner("Download Status: %d" % status)
                    sys.exit('Download Failed')

            return True

        except (urllib.error.URLError, OSError):
            retries_left -= 1
            print('download retry')
            time.sleep(delay_between_retries)

    print_banner("Download failed after retries")
    sys.exit('Download Failed')


def fetch_https_binary_file(url, filename, redirect, headers, cookie_file, netrc, connect_timeout) -> bool:
    """Fetches file via HTTPS as binary"""
    try:
        import pycurl
    except ImportError:
        return _fetch_https_binary_file_urllib(url, filename, redirect, headers, cookie_file, netrc, connect_timeout)

    import time

    retries_left = 3
    delay_between_retries = 5  # seconds
    success = False

    import certifi

    c = pycurl.Curl()
    c.setopt(pycurl.URL, url)
    c.setopt(pycurl.CAINFO, certifi.where())
    if connect_timeout is not None:
        c.setopt(pycurl.CONNECTTIMEOUT, connect_timeout)
    c.setopt(pycurl.NOSIGNAL, 1)
    c.setopt(pycurl.NOPROGRESS, False)
    c.setopt(pycurl.XFERINFOFUNCTION, fetch_https_progress)

    if headers:
        c.setopt(pycurl.HTTPHEADER, headers)

    if redirect:
        c.setopt(pycurl.FOLLOWLOCATION, 1)
        c.setopt(pycurl.AUTOREFERER, 1)
        c.setopt(pycurl.MAXREDIRS, 10)

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
            print('curl retry')
            time.sleep(delay_between_retries)

    status = c.getinfo(pycurl.HTTP_CODE)

    c.close()

    if not redirect and status == 302:
        print_banner("Download Status: %d" % status)
        return False
    if not status == 200:
        print_banner("Download Status: %d" % status)
        sys.exit('Download Failed')

    return success


def get_ws_folder():
    if "FLUTTER_WORKSPACE" in os.environ:
        workspace = os.environ.get('FLUTTER_WORKSPACE')
    else:
        workspace = os.getcwd()
    return workspace


def get_host_type() -> str:
    """returns host type in lower case"""
    return system().lower().rstrip()


def reset_sudo_timestamp():
    """invalidate sudo timestamp file"""
    # Skip sudo operations in CI environments with passwordless sudo
    if os.environ.get('CI') == 'true' and os.environ.get('GITHUB_ACTIONS') == 'true':
        return
    
    if get_host_type() == "linux":
        subprocess.check_call(['sudo', '-k'], stdout=subprocess.DEVNULL)


def validate_sudo_user_timestamp(args):
    """read password from standard input if available"""
    # Skip sudo validation in CI environments with passwordless sudo
    if os.environ.get('CI') == 'true' and os.environ.get('GITHUB_ACTIONS') == 'true':
        return
    
    if os.path.exists(args.stdin_file):
        with open(args.stdin_file) as stdin_file:
            if get_host_type() == "linux":
                subprocess.check_call(['sudo', '-S', '-v'], stdout=subprocess.DEVNULL, stdin=stdin_file)
    else:
        if get_host_type() == "linux":
            subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)


def validate_sudo_user():
    """update user's sudo timestamp without running a command"""
    # Skip sudo validation in CI environments with passwordless sudo
    if os.environ.get('CI') == 'true' and os.environ.get('GITHUB_ACTIONS') == 'true':
        return
    
    if get_host_type() == "linux":
        subprocess.check_call(['sudo', '-v'], stdout=subprocess.DEVNULL)


def chown_workspace(username, workspace):
    """chown workspace if linux"""
    if get_host_type() == "linux":
        cmd = ['sudo', 'chown', '-R', f'{username}:{username}', workspace]
        print(f'Changing ownership of workspace: {cmd}')
        subprocess.check_call(cmd, cwd=workspace, stdout=subprocess.DEVNULL)


def break_version(version):
    """ Break version string into major, minor, and patch """
    import re
    match = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?$', version)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2)) if match.group(2) else 0
        patch = int(match.group(3)) if match.group(3) else 0
        return major, minor, patch
    else:
        raise ValueError("Invalid version format")


def test_internet_connection() -> bool:
    """Test internet connection by connecting to nameserver"""
    try:
        import pycurl

        try:
            import certifi as _certifi
        except ImportError:
            _certifi = None

        c = pycurl.Curl()
        try:
            c.setopt(pycurl.URL, "https://dns.google")
            c.setopt(pycurl.FOLLOWLOCATION, 0)
            c.setopt(pycurl.CONNECTTIMEOUT, 5)
            c.setopt(pycurl.NOSIGNAL, 1)
            c.setopt(pycurl.NOPROGRESS, 1)
            c.setopt(pycurl.NOBODY, 1)
            if _certifi is not None:
                c.setopt(pycurl.CAINFO, _certifi.where())
            try:
                c.perform()
            except pycurl.error:
                pass

            res = False
            if c.getinfo(pycurl.RESPONSE_CODE) == 200:
                res = True
        finally:
            c.close()

        return res
    except ImportError:
        import urllib.request
        try:
            urllib.request.urlopen("https://dns.google", timeout=5)
            return True
        except (urllib.error.URLError, OSError):
            return False