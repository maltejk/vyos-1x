#!/bin/sh
# SRX: pin vyos1x-config to the commit the upstream Makefile uses, pin vyconf
# as upstream does, and cross build the C stub for the mips64el toolchain.
set -e
MK=$(readlink -f "${1:-Makefile}")
SRC=/tmp/vyos1x-config-src
rm -rf "$SRC"
git clone -q https://github.com/vyos/vyos1x-config.git "$SRC"
cd "$SRC"
# pinned commits: taken from the upstream 'depends' recipe in the Makefile ($1)
V1C=$(sed -n 's|.*vyos1x-config\.git#\([0-9a-f]*\).*|\1|p' "$MK")
[ -n "$V1C" ] || { echo 'vyos1x-config pin not found in Makefile' >&2; exit 1; }
git checkout -q "$V1C"
opam pin add vyos1x-config "$SRC" -y
# /vyos-src is a read-only bind mount owned by the host user. opam >= 2.6 runs git
# with GIT_CONFIG_GLOBAL=/dev/null (no safe.directory possible) and git refuses a
# foreign-owned repository, so pin a root-owned copy (cp -r: no ownership kept).
VC=/tmp/vyconf-src
rm -rf "$VC"
cp -r /vyos-src/vyconf "$VC"
opam pin add vyconf "$VC" -y
# SRX cross build: the same source for the mips64el findlib toolchain
# of the xcross image (docker/xcross/xocaml-setup.sh); bytecode, C stub cross built
if [ -f /opt/xocaml/dune-workspace ]; then
    dune build --workspace /opt/xocaml/dune-workspace -p vyos1x-config \
        _build/default.mips64el/vyos1x-config-mips64el.install
    cp -aL _build/install/default.mips64el/lib/. /opt/xocaml/lib/
fi
