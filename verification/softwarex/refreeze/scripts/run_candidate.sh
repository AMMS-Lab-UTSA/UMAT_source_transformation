#!/usr/bin/env bash
# Build one candidate commit of UMAT_source_transformation in an isolated venv
# and run the locally runnable evidence steps. Every step's exit status is
# recorded; failures are archived, not hidden.
#
# Usage: run_candidate.sh <commit> [steps]
#   steps: comma list from install,smoke,pytest,paper,psweep (default: all)
#
# Layout (relative to the manuscript workspace root):
#   refreeze/src/ust          read-only clone (push URL disabled)
#   refreeze/wt/<sha7>        detached worktree of the candidate
#   refreeze/venv/<sha7>      uv virtual environment (Python 3.11)
#   evidence/<sha7>/          archived logs, freeze, junit, outputs
set -u
WS="C:/Users/vfn333/Documents/GitHub/umat-oti-softwarex-manuscript"
COMMIT="$1"
STEPS="${2:-install,smoke,pytest,paper}"
CLONE="$WS/refreeze/src/ust"
SHA=$(git -C "$CLONE" rev-parse "$COMMIT^{commit}")
S7=${SHA:0:7}
WT="$WS/refreeze/wt/$S7"
VENV="$WS/refreeze/venv/$S7"
EV="$WS/evidence/$S7"
mkdir -p "$EV"
STATUS="$EV/step_status.tsv"
[ -f "$STATUS" ] || printf 'step\texit\tseconds\tstarted_utc\tcommand\n' > "$STATUS"

record() { # name exit seconds started command
  printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" >> "$STATUS"
}

run_step() { # name timeout_s command...
  local name="$1"; shift; local tmo="$1"; shift
  local t0=$(date +%s); local start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  ( cd "$WT" && timeout "$tmo" "$@" ) > "$EV/$name.log" 2>&1
  local rc=$?
  record "$name" "$rc" "$(( $(date +%s) - t0 ))" "$start" "$*"
  echo "[$S7] $name exit=$rc"
}

if [ ! -d "$WT" ]; then
  git -C "$CLONE" worktree add --detach "$WT" "$SHA" > "$EV/worktree.log" 2>&1
fi
PY="$VENV/Scripts/python.exe"
export PYTHONHASHSEED=0
export PYTHONDONTWRITEBYTECODE=1
export UV_LINK_MODE=copy

case ",$STEPS," in *,install,*)
  {
    echo "commit $SHA"
    git -C "$CLONE" log -1 --format='%ad %an %s' --date=iso "$SHA"
    echo "remote $(git -C "$CLONE" remote get-url origin)"
    uname -a; gfortran --version | head -1; gcc --version | head -1
  } > "$EV/environment.txt" 2>&1
  t0=$(date +%s); start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  uv venv --python 3.11.16 "$VENV" > "$EV/install.log" 2>&1
  extras="test"
  if git -C "$CLONE" show "$SHA:pyproject.toml" | grep -q '^paper *='; then extras="test,paper"; fi
  ( cd "$WT" && uv pip install --python "$PY" -e ".[${extras}]" ) >> "$EV/install.log" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then  # PyPI unreachable: resolve from the local uv cache
    echo "--- online install failed; retrying --offline (uv cache)" >> "$EV/install.log"
    ( cd "$WT" && uv pip install --offline --python "$PY" -e ".[${extras}]" ) >> "$EV/install.log" 2>&1
    rc=$?
  fi
  record install "$rc" "$(( $(date +%s) - t0 ))" "$start" "uv pip install -e .[${extras}]"
  SP="$VENV/Lib/site-packages"
  cp "$WS/refreeze/scripts/posix_shim/refreeze_posix_shim.py" "$SP/"
  echo "import refreeze_posix_shim" > "$SP/refreeze_posix_shim.pth"
  sha256sum "$WS/refreeze/scripts/posix_shim/refreeze_posix_shim.py" >> "$EV/environment.txt"
  # Harness-only plugins (parallel run, per-test timeout); not UMAT-OTI deps.
  # Wheels fetched once with curl into refreeze/src/wheels (uv could not reach
  # PyPI from this session); hashes in refreeze/MANIFEST.md.
  uv pip install --offline --find-links "$WS/refreeze/src/wheels" --python "$PY"     "pytest-xdist==3.8.0" "pytest-timeout==2.4.0" >> "$EV/install.log" 2>&1
  uv pip freeze --python "$PY" > "$EV/pip-freeze.txt" 2>&1
  "$PY" -c "import sys,numpy;print(sys.version);print('numpy',numpy.__version__)" >> "$EV/environment.txt" 2>&1
  echo "[$S7] install exit=$rc"
;; esac

case ",$STEPS," in *,smoke,*)
  if [ -f "$WT/src/umat_oti/reproduce.py" ]; then
    run_step smoke 1800 "$PY" -m umat_oti.reproduce --profile smoke --out-dir "$EV/reproduce-smoke"
  else
    record smoke NA 0 - "no src/umat_oti/reproduce.py at this commit"
  fi
;; esac

case ",$STEPS," in *,pytest,*)
  # Parallel first pass (8 xdist workers, whole files per worker; the machine
  # is shared), per-test timeout 900 s; then a serial re-run of only the
  # failures, so parallel-only artefacts are separable from real failures.
  run_step pytest 21600 "$PY" -m pytest -q -n 8 --dist loadfile --timeout 900 \
    -o cache_dir="$EV/.pytest_cache" -m "not abaqus and not arc and not network" \
    --junitxml="$EV/pytest-junit.xml" -o junit_family=xunit2 -rfE
  tail -n 400 "$EV/pytest.log" | grep -E "passed|failed|error" | tail -n 1 > "$EV/pytest-summary.txt"
  run_step pytest_rerun_failed_serial 21600 "$PY" -m pytest -q -p no:xdist --timeout 900 \
    -o cache_dir="$EV/.pytest_cache" --lf --last-failed-no-failures none \
    -m "not abaqus and not arc and not network" \
    --junitxml="$EV/pytest-rerun-junit.xml" -o junit_family=xunit2 -rfE
  tail -n 400 "$EV/pytest_rerun_failed_serial.log" | grep -E "passed|failed|error|no tests ran" | tail -n 1 >> "$EV/pytest-summary.txt"
;; esac

case ",$STEPS," in *,paper,*)
  if [ -f "$WT/src/umat_oti/reproduce.py" ]; then
    run_step paper 7200 "$PY" -m umat_oti.reproduce --profile paper --out-dir "$EV/reproduce-paper"
  else
    record paper NA 0 - "no src/umat_oti/reproduce.py at this commit"
  fi
;; esac

case ",$STEPS," in *,psweep,*)
  run_step psweep 7200 "$PY" tools/run_parameter_sensitivity_sweep.py --help
;; esac
echo "[$S7] done"
