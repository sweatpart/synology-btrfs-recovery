#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
[[ $(id -u) -ne 0 ]] || { echo 'Do not build as root' >&2; exit 2; }
for c in git python3 make gcc pkg-config; do command -v "$c" >/dev/null || { echo "Missing $c" >&2; exit 2; }; done
if [[ ! -e upstream-btrfs-progs/.git ]]; then
  git clone --depth 1 --branch v6.17.1 https://github.com/kdave/btrfs-progs.git upstream-btrfs-progs
fi
[[ $(git -C upstream-btrfs-progs describe --tags --exact-match HEAD 2>/dev/null) == v6.17.1 ]] || { echo 'Wrong upstream tag' >&2; exit 2; }
python3 patch_upstream.py upstream-btrfs-progs/kernel-shared/tree-checker.c
git -C upstream-btrfs-progs diff -- kernel-shared/tree-checker.c > synology-compat-generated.patch
# Configure without Python to support newer Python versions lacking pythonX.Y.pc
if ( cd upstream-btrfs-progs; ./autogen.sh && ./configure --disable-python --disable-documentation --disable-static && make -j2 btrfs ) > build.log 2>&1; then
  upstream-btrfs-progs/btrfs --version
else
  tail -n 60 build.log >&2; exit 1
fi
