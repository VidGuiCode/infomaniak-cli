#!/usr/bin/env bash
# Built-package install smoke test for infomaniak-cli.
#
# Builds the wheel, installs it into a THROWAWAY venv (never global, never
# pipx/uv tool), and verifies the installed `ik` command works. Does not touch
# your global environment or your real config — it uses an isolated temp dir.
#
# Usage:
#   bash scripts/smoke_install.sh
#
# Requires: uv (for the build) and python3 (for the throwaway venv). Network is
# only used by `uv build`'s backend if not already cached; the install itself
# uses the local wheel only (--no-index).
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

work_dir="$(mktemp -d)"
cleanup() { rm -rf "$work_dir"; }
trap cleanup EXIT

echo "==> Building wheel into $work_dir/dist"
uv build --wheel --out-dir "$work_dir/dist"

wheel="$(ls "$work_dir"/dist/infomaniak_cli-*-py3-none-any.whl | head -n 1)"
echo "==> Built wheel: $wheel"

echo "==> Creating throwaway venv"
python3 -m venv "$work_dir/venv"

# Resolve the venv's python/bin path cross-platform (POSIX vs Windows layout).
if [ -x "$work_dir/venv/bin/python" ]; then
  venv_python="$work_dir/venv/bin/python"
else
  venv_python="$work_dir/venv/Scripts/python.exe"
fi

echo "==> Installing the freshly built wheel (local wheel only, no index)"
"$venv_python" -m pip install --quiet --no-index --find-links "$work_dir/dist" "$wheel"

# Isolated config dir so the smoke run never reads or writes your real profiles.
export IK_CONFIG_DIR="$work_dir/config"

echo "==> ik version"
"$venv_python" -m infomaniak_cli.cli version

echo "==> ik --help"
"$venv_python" -m infomaniak_cli.cli --help >/dev/null

echo "==> ik setup --profile test --non-interactive"
"$venv_python" -m infomaniak_cli.cli setup --profile test --non-interactive

echo "==> ik doctor --json"
"$venv_python" -m infomaniak_cli.cli doctor --json >/dev/null

echo "PASS: built wheel installs and runs in a throwaway venv."
