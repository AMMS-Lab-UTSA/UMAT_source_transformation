#!/usr/bin/env bash
# Run the three evidence-generating rounds of the `paper` profile directly
# (without the profile's embedded full test suite) for one candidate commit
# whose venv/worktree already exist (run_candidate.sh install).
#   parameter-sensitivity sweep (Table 6 / L38), internal-Jacobian round
#   (Table 3 / L27-L28), tangent + higher-order round (Tables 2/5, L21-L22).
# Results go to evidence/<sha7>/rounds/<round>/; exit status per step.
# Usage: run_rounds.sh <commit>
set -u
WS="C:/Users/vfn333/Documents/GitHub/umat-oti-softwarex-manuscript"
SHA=$(git -C "$WS/refreeze/src/ust" rev-parse "$1^{commit}")
S7=${SHA:0:7}
WT="$WS/refreeze/wt/$S7"
PY="$WS/refreeze/venv/$S7/Scripts/python.exe"
EV="$WS/evidence/$S7"
R="$EV/rounds"
mkdir -p "$R"
STATUS="$EV/step_status.tsv"
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1

step() { # name timeout command...
  local name="$1"; shift; local tmo="$1"; shift
  local t0=$(date +%s) start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  ( cd "$WT" && timeout "$tmo" "$@" ) > "$R/$name.log" 2>&1
  local rc=$?
  printf '%s\t%s\t%s\t%s\t%s\n' "round_$name" "$rc" "$(( $(date +%s) - t0 ))" "$start" "$*" >> "$STATUS"
  echo "[$S7] round $name exit=$rc"
}

step psweep 7200 "$PY" tools/run_parameter_sensitivity_sweep.py \
  --work-dir "$R/psweep/work" --results-dir "$R/psweep/results"
step internal_jacobian 7200 "$PY" tools/run_internal_jacobian_round.py \
  --work-dir "$R/internal_jacobian/work" --results-dir "$R/internal_jacobian/results"
step tangent 7200 "$PY" tools/run_tangent_round.py \
  --work-dir "$R/tangent/work" --results-dir "$R/tangent/results"
echo "[$S7] rounds done"
