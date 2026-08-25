#!/usr/bin/env bash
# Prove that a fresh clone reproduces without anything from the developer's
# machine.
#
# The working tree this was developed in benefits from many local files: build
# directories, an already-populated workspace, models copied from elsewhere, a
# virtual environment with the package already importable. None of that may be
# required. This script clones the pushed branch into a temporary directory,
# builds a new virtual environment, installs from pyproject.toml alone, and runs
# the reproduction there.
#
# It deliberately does NOT copy anything across, and it checks afterwards that
# nothing in the clone points back at the development tree.
#
# Usage:
#   scripts/clean_clone_acceptance.sh [--branch NAME] [--keep] [--profile NAME]

set -euo pipefail

BRANCH="${BRANCH:-}"
PROFILE="smoke"
KEEP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)  BRANCH="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --keep)    KEEP=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="${BRANCH:-$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)}"
ORIGIN="$(git -C "$REPO_ROOT" remote get-url origin)"
EXPECTED="$(git -C "$REPO_ROOT" rev-parse HEAD)"

WORK="$(mktemp -d -t umat-oti-clean-clone-XXXXXX)"
cleanup() { [[ "$KEEP" -eq 1 ]] || rm -rf "$WORK"; }
trap cleanup EXIT

echo "==> clean-clone acceptance"
echo "    branch:  $BRANCH"
echo "    scratch: $WORK"
[[ "$KEEP" -eq 1 ]] && echo "    (--keep: the clone will be left in place)"

step() { printf '\n--- %s\n' "$1"; }

step "1. clone the branch (no local files carried across)"
git clone --quiet --branch "$BRANCH" --single-branch "$ORIGIN" "$WORK/clone"
CLONE="$WORK/clone"
ACTUAL="$(git -C "$CLONE" rev-parse HEAD)"
echo "    cloned $ACTUAL"
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "    NOTE: local HEAD is $EXPECTED; the clone has $ACTUAL." >&2
  echo "    The clean clone tests what is pushed, not what is uncommitted." >&2
fi

step "2. initialise permissive submodules (restricted tiers must stay empty)"
git -C "$CLONE" submodule update --init --recursive 2>&1 | sed 's/^/    /' || true

step "3. create a fresh virtual environment"
"${PYTHON:-python3}" -m venv "$WORK/venv"
VENV_PY="$WORK/venv/bin/python"
"$VENV_PY" -m pip install --quiet --upgrade pip

step "4. install from pyproject.toml alone"
"$VENV_PY" -m pip install --quiet -e "$CLONE[test]"
"$VENV_PY" -c "import umat_oti; print('    umat_oti imported from', umat_oti.__file__)"

step "5. run the $PROFILE reproduction profile"
( cd "$CLONE" && "$VENV_PY" -m umat_oti.reproduce --profile "$PROFILE" \
    --out-dir "$WORK/reproduce" )

step "6. run the offline test suite"
( cd "$CLONE" && "$VENV_PY" -m pytest -q \
    -m "not abaqus and not arc and not network" ) | tail -5

step "7. compile representative Fortran"
if command -v gfortran >/dev/null 2>&1; then
  ( cd "$CLONE" && "$VENV_PY" -m pytest -q -m fortran ) | tail -3
else
  echo "    blocked_by_external_dependency: gfortran is not on PATH"
fi

step "8. repository-standards audit inside the clone"
( cd "$CLONE" && "$VENV_PY" tools/audit_repository_standards.py ) | tail -10

step "9. check the required reproduction artefacts exist"
missing=0
for name in run_manifest.json environment.json claim_matrix.json \
            artifact_checksums.sha256 reproduction_summary.md; do
  if [[ -f "$WORK/reproduce/$name" ]]; then
    echo "    present: $name"
  else
    echo "    MISSING: $name" >&2; missing=1
  fi
done
[[ "$missing" -eq 0 ]] || { echo "clean-clone FAILED: missing artefacts" >&2; exit 1; }

step "10. confirm nothing in the clone depends on the development tree"
# Any reference to the developer's working directories would mean the clone is
# not self-contained. Archived run records are exempt for the reasons stated in
# tools/repository_standards.json, and the audit above already enforced that.
# The exempt prefixes come from tools/repository_standards.json so this check
# and the audit cannot drift apart. Each exemption there states why the path is
# a record of a past run rather than an input to a reproduction.
mapfile -t EXEMPT < <("$VENV_PY" - "$CLONE" <<'PYEOF'
import json, sys
from pathlib import Path
config = Path(sys.argv[1]) / "tools" / "repository_standards.json"
for entry in json.loads(config.read_text())["absolute_path_exemptions"]:
    print(entry["prefix"])
PYEOF
)
printf '    exempt prefixes: %s\n' "${EXEMPT[*]}"

leaks="$(grep -rIl --exclude-dir=.git \
    -e "$REPO_ROOT" -e "$HOME/softwarex_work" -e "$HOME/Documents" \
    -e "$HOME/Desktop" "$CLONE" 2>/dev/null || true)"
for prefix in "${EXEMPT[@]}"; do
  leaks="$(printf '%s\n' "$leaks" | grep -v "^$CLONE/$prefix" || true)"
done
leaks="$(printf '%s\n' "$leaks" | sed '/^$/d')"
if [[ -n "$leaks" ]]; then
  echo "    FAILED: these files reference the development tree:" >&2
  echo "$leaks" | sed 's/^/      /' >&2
  exit 1
fi
echo "    no file outside archived run records references the development tree"

printf '\n==> clean-clone acceptance PASSED (%s, profile %s)\n' "$BRANCH" "$PROFILE"
