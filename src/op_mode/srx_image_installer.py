#!/usr/bin/env python3
#
# Image installation on the Juniper SRX300 (U-Boot slot layout, no GRUB).
# 'install image' runs the installer shipped on the live media (<src>/install/install-to-eusb.sh)
# and asks for confirmation like the x86 installer does.

import os
import subprocess
import sys

from vyos.utils.io import ask_yes_no

LIVE_SRC = os.environ.get('SRX_LIVE_SRC', '/run/live/src')


def is_srx() -> bool:
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


def add_image() -> None:
    sys.exit('add system image: not supported on the SRX300 yet; '
             'use "install image" from the installer media.')
