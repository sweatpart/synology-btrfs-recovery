#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"

usage() {
  cat <<'EOF'
Usage: ./setup.sh [--system] [--build]

  (none)    Create local .venv and run logic tests; no sudo or network required.
  --system  Install Ubuntu/Debian apt system dependencies (uses sudo).
  --build   Build patched, pinned btrfs-progs v6.17.1 (network required).

Use --system first on a fresh Ubuntu host, then ./setup.sh --build.
No PyPI runtime dependencies; requirements.txt intentionally contains no packages.
EOF
}
SYSTEM=0; BUILD=0
for arg in "$@"; do
  case "$arg" in
    --system) SYSTEM=1 ;;
    --build) BUILD=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done
if (( SYSTEM )); then
  command -v apt-get >/dev/null || { echo 'The --system mode requires Ubuntu/Debian apt-get' >&2; exit 2; }
  (( EUID != 0 )) || { echo 'Run as a normal user with sudo, not root' >&2; exit 2; }
  sudo apt-get update
  sudo apt-get install -y \
    python3 python3-venv python3-pip git build-essential autoconf automake \
    pkg-config libtool libblkid-dev libuuid1 uuid-dev libzstd-dev liblz4-dev \
    zlib1g-dev libudev-dev libmount-dev libacl1-dev libattr1-dev libext2fs-dev \
    mdadm lvm2 smartmontools util-linux
fi
command -v python3 >/dev/null || { echo 'Missing python3; use ./setup.sh --system' >&2; exit 2; }
if [[ ! -f .venv/pyvenv.cfg ]]; then
  python3 -m venv .venv || { echo 'Virtualenv creation failed. On Ubuntu: sudo apt install python3-venv' >&2; exit 2; }
fi
PYTHON="$PWD/.venv/bin/python"
"$PYTHON" -m pip --version >/dev/null 2>&1 || echo 'Note: pip not present; runtime needs only Python standard library.'
# No pip install: requirements.txt has no third-party packages.
"$PYTHON" -m unittest discover -s tests -v
if (( BUILD )); then
  ./build.sh
fi
printf '\nSetup complete. Activate with: source .venv/bin/activate\n'
printf 'Or run directly: .venv/bin/python synology_ro.py --help\n'
