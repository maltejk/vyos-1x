#!/usr/bin/env python3
#
# Image installation on the Juniper SRX300 (U-Boot slot layout, no GRUB).
# 'install image' runs the installer shipped on the live media (<src>/install/install-to-eusb.sh)
# and asks for confirmation like the x86 installer does.
# 'add system image' installs a release tar (format 2: squashfs + U-Boot shim/kernel boot files + MANIFEST) as a
# new slot on the running system's SRXBOOT/VYOSDATA disk via /usr/libexec/vyos/slot-install.sh; show/delete/set
# image use the same slot layout.

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlparse, urlunparse

LIVE_SRC = os.environ.get('SRX_LIVE_SRC', '/run/live/src')


def is_srx() -> bool:
    if os.environ.get('SRX_FORCE'):   # smoke test on qemu malta: same slot layout, no device tree
        return True
    try:
        with open('/proc/device-tree/compatible', 'rb') as f:
            return b'juniper,srx300' in f.read()
    except OSError:
        return False


def _installer() -> str:
    global LIVE_SRC
    script = os.path.join(LIVE_SRC, 'install', 'install-to-eusb.sh')
    if not os.path.isfile(script):
        # systemd mounts a fresh tmpfs on /run, hiding the initramfs mount: mount the media again
        mnt = '/mnt/instdata'
        subprocess.run(['sudo', 'mkdir', '-p', mnt])
        if (os.path.ismount(mnt) or subprocess.run(
                ['sudo', 'mount', 'LABEL=INSTDATA', mnt],
                capture_output=True).returncode == 0):
            LIVE_SRC = mnt
            script = os.path.join(LIVE_SRC, 'install', 'install-to-eusb.sh')
    if not os.path.isfile(script):
        sys.exit('No installer media found: this system is not running live '
                 f'from an installer stick ({script} missing).')
    return script


def install_image() -> None:
    from vyos.utils.io import ask_yes_no
    script = _installer()
    plan = subprocess.run(['sudo', 'env', f'SRC={LIVE_SRC}', 'sh', script], capture_output=True, text=True)
    log = os.path.join(LIVE_SRC, 'install', 'install.log')
    try:
        with open(log) as f:
            lines = [l.strip() for l in f if l.startswith('Stick=') or l.startswith('FAIL')]
    except OSError:
        lines = []
    if plan.returncode != 0 or not lines or lines[-1].startswith('FAIL'):
        sys.exit(f'Installer check failed: {lines[-1] if lines else plan.stderr.strip()}')
    print(lines[-1])
    print('WARNING: the internal eUSB will be repartitioned; ALL data on it '
          '(e.g. Junos) is erased. Back it up first.')
    if not ask_yes_no('Install VyOS to the internal eUSB?', default=False):
        sys.exit('Installation aborted.')
    res = subprocess.run(['sudo', 'env', f'SRC={LIVE_SRC}', 'sh', script, '-y'])
    result = os.path.join(LIVE_SRC, 'install', 'result.txt')
    try:
        out = open(result).read().strip()
    except OSError:
        out = 'no result file'
    if res.returncode != 0 or not out.startswith('INSTALL-OK'):
        sys.exit(f'Installation failed: {out} (log: {log})')
    print(out)
    print('Remove the installer media and reboot: it boots from the eUSB.')


# ---------------------------------------------------------------------------------------------
# slot layout (SRXBOOT p1 + VYOSDATA p2 on one disk, tools/vyos/slot-install.sh)

LIBEXEC = os.environ.get('SRX_LIBEXEC', '/usr/libexec/vyos')
SLOT_INSTALL = os.path.join(LIBEXEC, 'slot-install.sh')
SHM = '/dev/shm'
NAME_RE = re.compile(r'^[\w.+-]{1,64}$')
# placeholder board identity of the shim in the release tar (ci/slot-boot.sh); the installer replaces it with the
# running board's serial/MAC, copied from the shim of the running slot
PH_SERIAL = b'SRX300-IDENTITY'.ljust(20, b'\0')
PH_MAC = bytes.fromhex('020000000000')


def rev8(b: bytes) -> bytes:
    b = b + b'\0' * (-len(b) % 8)
    return b''.join(b[i:i + 8][::-1] for i in range(0, len(b), 8))


def _blocks(serial: bytes, mac: bytes):
    # boot info copy (doubleword-reversed) and boot descriptor copy (plain), as boot/gen_boot_le.py writes them
    return rev8(serial + mac + b'\x08'), serial + mac


def patch_identity(new_shim: bytes, old_shim: bytes) -> bytes:
    """Return new_shim with the board identity (serial, MAC) of old_shim (a shim made by the same generator)."""
    b1, b2 = _blocks(PH_SERIAL, PH_MAC)
    if new_shim.count(b1) != 1 or new_shim.count(b2) != 1:
        raise ValueError('image shim has no unique identity placeholder')
    o1, o2 = new_shim.index(b1), new_shim.index(b2)
    old1, old2 = old_shim[o1:o1 + len(b1)], old_shim[o2:o2 + len(b2)]
    if len(old1) != len(b1) or len(old2) != len(b2) or rev8(old1)[:len(b2)] != old2:
        raise ValueError('cannot read the board identity from the running slot')
    if old2 == b2 or not any(old2[20:26]):
        raise ValueError('the running slot has no board identity')
    return new_shim[:o1] + old1 + new_shim[o1 + len(b1):o2] + old2 + new_shim[o2 + len(b2):]


def parse_manifest(text: str) -> tuple:
    """-> (keys, sums): key=value header, {file: sha256} (sha lines before the 'packages:' list)"""
    keys, sums = {}, {}
    for line in text.split('\n'):
        if line.startswith('packages:'):
            break
        m = re.match(r'^([0-9a-f]{64})  (\S+)$', line)
        if m:
            sums[m.group(2)] = m.group(1)
        elif '=' in line and not sums:
            k, v = line.split('=', 1)
            keys[k] = v
    return keys, sums


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def extract_tar(tar_path: str, dest: str) -> tuple:
    """Extract MANIFEST and the files it names for a format-2 image into dest, verify their sums -> (keys, ver)"""
    with tarfile.open(tar_path) as t:
        names = t.getnames()
        if 'MANIFEST' not in names:
            raise ValueError('not an SRX300 image tar (no MANIFEST)')
        mf = t.extractfile('MANIFEST').read().decode()
        keys, sums = parse_manifest(mf)
        if keys.get('format') != '2':
            raise ValueError('this image tar has no boot files (MANIFEST format 2 needed); '
                             'use the manual steps in docs/install-srx300-image.md')
        ver = keys.get('version', '')
        want = [keys.get('squashfs'), keys.get('shim'), keys.get('kernelbin')]
        if not NAME_RE.match(ver) or not all(want) or keys.get('arch') != 'mips64el':
            raise ValueError('MANIFEST is incomplete or not for mips64el')
        for n in want:
            if n not in names or n not in sums or '/' in n:
                raise ValueError(f'MANIFEST/tar mismatch for {n}')
            if not t.getmember(n).isreg():
                raise ValueError(f'{n} is not a regular file')
            t.extract(t.getmember(n), dest)
    for n in want:
        if sha256_file(os.path.join(dest, n)) != sums[n]:
            raise ValueError(f'SHA256 mismatch for {n}: damaged or modified image')
    return keys, ver


def _redact(url: str) -> str:
    u = urlparse(url)
    return urlunparse(u._replace(netloc=u.netloc.rpartition('@')[2])) if '@' in u.netloc else url


def _download(local: str, url: str, vrf, check_space: bool = False) -> None:
    # credentials travel in REMOTE_USERNAME/REMOTE_PASSWORD (HTTP basic auth in vyos.remote)
    if vrf is None:
        from vyos.remote import download
        download(local, url, progressbar=True, check_space=check_space, raise_error=True)
    else:
        from vyos.defaults import base_dir
        subprocess.run(['sudo', '-E', 'ip', 'vrf', 'exec', vrf, f'{base_dir}/simple-download.py',
                        '--local-file', local, '--remote-path', url], check=True)


def _sudo(*cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(['sudo', *cmd], **kw)


def running_slot() -> str:
    m = re.search(r'(?:^|\s)live\.slot=(\S+)', open('/proc/cmdline').read())
    return m.group(1) if m else ''


def find_disk() -> str:
    """Disk holding the SRXBOOT and VYOSDATA partitions (exactly one such disk, else refuse)"""
    out = subprocess.run(['lsblk', '-rno', 'NAME,LABEL,PKNAME'], capture_output=True, text=True).stdout
    disks = {}
    for line in out.splitlines():
        f = line.split()
        if len(f) == 3 and f[1] in ('SRXBOOT', 'VYOSDATA'):
            disks.setdefault(f[2], set()).add(f[1])
    ok = [d for d, labels in disks.items() if labels == {'SRXBOOT', 'VYOSDATA'}]
    if len(ok) != 1:
        sys.exit('Cannot find a unique disk with partitions SRXBOOT and VYOSDATA '
                 f'(found: {", ".join(ok) or "none"}); is this system installed in the slot layout?')
    return f'/dev/{ok[0]}'


def slot_cmd(*args: str, env=(), **kw) -> subprocess.CompletedProcess:
    return _sudo('env', *env, 'bash', SLOT_INSTALL, *args, **kw)


def list_slots(disk: str) -> tuple:
    r = slot_cmd('list', disk, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f'Cannot read the slots of {disk}: {r.stderr.strip()}')
    lines = r.stdout.strip().splitlines()
    default = lines[0].split(': ', 1)[1].strip() if lines else ''
    return default, [l.split() for l in lines[1:]]   # [name, size]


def add_image(image_path: str, vrf: str = None, username: str = '', password: str = '',
              no_prompt: bool = False, force: bool = False) -> None:
    from vyos.config_mgmt import unsaved_commits
    from vyos.utils.io import ask_yes_no

    running = running_slot()
    if not running or 'live.src=LABEL=VYOSDATA' not in open('/proc/cmdline').read():
        sys.exit('This system is not running from an installed slot; use "install image" first.')
    if unsaved_commits():
        if no_prompt:
            sys.exit('There are unsaved configuration changes; save them first.')
        if not ask_yes_no('There are unsaved configuration changes. Continue anyway?', default=False):
            sys.exit()
    if shutil.disk_usage(SHM).free < 700 * 2**20:
        sys.exit(f'Not enough free memory in {SHM} (700 MiB needed for download and unpacking).')
    disk = find_disk()
    os.environ['REMOTE_USERNAME'] = username
    os.environ['REMOTE_PASSWORD'] = password

    work = tempfile.mkdtemp(prefix='srx-add.', dir=SHM)
    try:
        if urlparse(image_path).scheme:
            tar = os.path.join(work, 'image.tar')
            print(f'Downloading {_redact(image_path)}')
            try:
                _download(tar, image_path, vrf, check_space=True)
            except Exception as e:
                sys.exit(f'The image cannot be fetched from {_redact(image_path)}: {e}')
            sums_url = image_path.rsplit('/', 1)[0] + '/SHA256SUMS'
            sums = os.path.join(work, 'SHA256SUMS')
            try:
                _download(sums, sums_url, vrf)
            except Exception:
                sums = None
            name = image_path.rsplit('/', 1)[1].split('?')[0]
        else:
            tar, name = image_path, os.path.basename(image_path)
            sums = os.path.join(os.path.dirname(os.path.abspath(tar)), 'SHA256SUMS')
            sums = sums if os.path.isfile(sums) else None
        if not os.path.isfile(tar):
            sys.exit(f'The image cannot be fetched from {image_path}: no such file')
        if sums:
            want = {l.split()[1].lstrip('*'): l.split()[0] for l in open(sums) if len(l.split()) == 2}
            if name not in want:
                sys.exit(f'SHA256SUMS has no entry for {name}')
            if sha256_file(tar) != want[name]:
                sys.exit('Image checksum verification failed.')
            print('SHA256SUMS verified')
        elif not no_prompt and not ask_yes_no('No SHA256SUMS found next to the image. Continue without checking it?',
                                              default=False):
            sys.exit('Installation aborted.')
        print('Validating image')
        try:
            keys, ver = extract_tar(tar, work)
        except (ValueError, tarfile.TarError) as e:
            sys.exit(f'Invalid image: {e}')
        if tar.startswith(work):
            os.unlink(tar)   # the tmpfs holds squashfs + tar otherwise
        default, slots = list_slots(disk)
        if ver in [s[0] for s in slots]:
            sys.exit(f'The image "{ver}" is already installed.')
        need = os.path.getsize(os.path.join(work, keys['squashfs'])) // 2**20 + 60
        free = int(slot_cmd('free', disk, capture_output=True, text=True).stdout.strip() or 0)
        if free < need:
            sys.exit(f'Not enough space on VYOSDATA ({free} MiB free, {need} MiB needed); '
                     'remove an old image with "delete system image".')
        old = _sudo('env', 'bash', SLOT_INSTALL, 'shim', disk, running if running in [s[0] for s in slots] else default,
                    capture_output=True)
        try:
            shim = patch_identity(open(os.path.join(work, keys['shim']), 'rb').read(), old.stdout)
        except ValueError as e:
            sys.exit(f'Cannot set the board identity: {e}')
        open(os.path.join(work, keys['shim']), 'wb').write(shim)
        # the slot is named after the image version: live.slot=<ver> is part of the kernel command line in the boot files
        set_default = no_prompt or ask_yes_no(f'Would you like to set the new image "{ver}" as the default one for boot?',
                                              default=True)
        migrate = no_prompt or ask_yes_no('Would you like to save the current configuration and SSH host keys '
                                          'to the new image?', default=True)
        print(f'Installing slot {ver} (this takes a few minutes on the eUSB)')
        env = ['NODEFAULT=1'] + (['MIGRATE=1'] if migrate else [])
        pre = os.path.join(work, 'slot-' + ver)
        os.rename(os.path.join(work, keys['shim']), pre + '.shim.bin')
        os.rename(os.path.join(work, keys['kernelbin']), pre + '.kernel.bin')
        if slot_cmd('add', disk, ver, os.path.join(work, keys['squashfs']), pre, env=env).returncode:
            sys.exit(f'Installing the image "{ver}" failed; the default image is unchanged.')
        if set_default and slot_cmd('default', disk, ver).returncode:
            sys.exit(f'Setting "{ver}" as default failed; the default image is unchanged.')
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f'The image "{ver}" was added.' + (' It is the default boot image.' if set_default else ''))
    print('Reboot to start it ("reboot"); the first boot takes a few minutes.')


def _annotated(disk: str) -> list:
    default, slots = list_slots(disk)
    run = running_slot()
    return [[n, size, 'Yes' if n == default else '', 'Yes' if n == run else ''] for n, size in slots], default, run


def show(raw: bool):
    from tabulate import tabulate
    rows, default, run = _annotated(find_disk())
    if raw:
        return {'image_default': default, 'image_running': run, 'images_available': [r[0] for r in rows]}
    return tabulate([[r[0], r[2], r[3]] for r in rows], ['Name', 'Default boot', 'Running'], disable_numparse=True)


def show_details(raw: bool):
    from tabulate import tabulate
    rows, _, _ = _annotated(find_disk())
    if raw:
        return [{'name': r[0], 'size': r[1]} for r in rows]
    return tabulate([[r[0], r[0], r[1]] for r in rows], ['Name', 'Version', 'Storage'], disable_numparse=True)


def manage(action: str, image_name: str = None, no_prompt: bool = False) -> None:
    """delete/set/list for `delete system image`, `set system image default-boot`, `show system image`"""
    from vyos.utils.io import ask_yes_no, select_entry
    if action not in ('delete', 'set', 'list'):
        sys.exit(f'"{action}" is not supported on the SRX300.')
    disk = find_disk()
    rows, default, run = _annotated(disk)
    names = [r[0] for r in rows]
    if action == 'list':
        print('\n'.join(names))
        return
    label = {r[0]: r[0] + (' (running)' if r[3] else '') + (' (default boot)' if r[2] else '') for r in rows}
    if image_name is None:
        if no_prompt:
            sys.exit(f'An image name is required for {action} action')
        image_name = select_entry(names, 'The following images are installed:',
                                  f'Select an image to {"delete" if action == "delete" else "set as default"}:',
                                  lambda n: label[n])
    if image_name not in names:
        sys.exit(f'The image "{image_name}" cannot be found')
    if action == 'set':
        if image_name == default:
            sys.exit(f'The image "{image_name}" already configured as default')
        if slot_cmd('default', disk, image_name).returncode:
            sys.exit(f'Unable to set default image "{image_name}"')
        print(f'The image "{image_name}" is now default boot image')
        return
    if image_name == run:
        sys.exit('Currently running image cannot be deleted; reboot into another image first')
    if image_name == default:
        sys.exit('Default image cannot be deleted; set another image as default first')
    if not no_prompt and not ask_yes_no(f'Do you really want to delete the image {image_name}?', default=False):
        sys.exit()
    if slot_cmd('del', disk, image_name).returncode:
        sys.exit(f'Unable to remove the image "{image_name}"')
    print(f'The image "{image_name}" was successfully deleted')
