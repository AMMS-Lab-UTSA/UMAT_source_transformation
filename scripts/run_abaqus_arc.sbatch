#!/bin/bash
#SBATCH --job-name=umat-oti-abaqus
#SBATCH --partition=compute1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --time=00-01:00:00
#SBATCH --output=logs/umat-oti-abaqus-%j.out
#SBATCH --error=logs/umat-oti-abaqus-%j.err

# ============================================================================
# ARC Slurm submission script for the UMAT-OTI Abaqus paired validation.
#
# What this does (in order):
#   1. Records the compute-node environment (compiler + Abaqus versions).
#   2. Runs the OTI Fortran material-point verification (Priority 1+2+3):
#        DSIGMA_DP / DSTATEV_DP OTI-vs-FD (parameter_sensitivity_j2)
#        higher-order OTI-vs-SymPy (higher_order_strain)
#      These do NOT need Abaqus and can complete even if the Abaqus module
#      fails to load; they just need gfortran on PATH.
#   3. Runs the 19-contract transformation batch with --validate, which
#      shells out to Abaqus for the original vs transformed UMAT paired
#      comparison (STRESS / STATEV / DDSDDE / CONVERGENCE) on every
#      contract that carries a validation block.
#   4. Runs the unified validator run_suite so the environment-detection
#      report + honest 'blocked' / 'passed' stage summary is captured.
#
# Nothing in this script guesses a partition, account, or wall-time. Edit
# the SBATCH directives above to match your ARC allocation, or submit with:
#
#   sbatch --partition=<part> --account=<acct> --time=00-02:00:00 \
#          scripts/run_abaqus_arc.sbatch
#
# When Abaqus is unreachable the script writes a 'blocked' report rather
# than failing silently, so a later rerun with an actual Abaqus module can
# be attempted without re-editing anything.
# ============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "${REPO_ROOT}"

LOG_DIR="${REPO_ROOT}/logs"
mkdir -p "${LOG_DIR}"

RESULT_DIR="${REPO_ROOT}/paper_results/arc_${SLURM_JOB_ID:-manual}"
mkdir -p "${RESULT_DIR}"

echo "[$(date -Iseconds)] ARC UMAT-OTI validation start; result_dir=${RESULT_DIR}"

# --- 1. Environment metadata -------------------------------------------------
if command -v module >/dev/null 2>&1; then
    # ARC modules: the OTI Fortran generator needs gfortran >= 10 because the
    # bundled pyoti template uses RANK(ARRAY) in declarations. The transform
    # pipeline's helper post-fix compensates for older compilers, but a modern
    # gcc is still preferred.
    module load gcc/13.3.0 || module load gcc/12.4.0 || true
    module load intel/oneapi/2024.2.0.634 || true
    module load abaqus/2024 || {
        echo "[$(date -Iseconds)] WARNING: abaqus/2024 module load failed"
    }
fi

{
    echo "hostname=$(hostname)"
    echo "date=$(date -Iseconds)"
    echo "gfortran_path=$(command -v gfortran || echo NOT_FOUND)"
    gfortran --version 2>/dev/null || echo "gfortran not found"
    echo "abaqus_path=$(command -v abaqus || echo NOT_FOUND)"
    abaqus information=system 2>/dev/null || echo "abaqus information=system failed"
    echo "python=$(command -v python || command -v python3)"
} > "${RESULT_DIR}/system.txt"

# --- 2. OTI Fortran material-point verification ------------------------------
python -m umat_oti.reports.run_softwarex_evidence \
    --output-dir "${RESULT_DIR}/evidence" \
    > "${RESULT_DIR}/evidence.stdout.json" \
    || echo "[$(date -Iseconds)] evidence command exited non-zero"

# --- 3. Abaqus paired batch --------------------------------------------------
if command -v abaqus >/dev/null 2>&1; then
    python tools/run_completed_json_batch.py \
        --validate \
        --abaqus-command abaqus \
        --batch-dir "${RESULT_DIR}/paired_batch" \
        > "${RESULT_DIR}/paired_batch.stdout.txt" \
        2> "${RESULT_DIR}/paired_batch.stderr.txt" \
        || echo "[$(date -Iseconds)] paired batch exited non-zero"
else
    echo "abaqus not on PATH after module load; skipping paired batch" \
        > "${RESULT_DIR}/paired_batch.blocked.txt"
fi

# --- 4. Unified validator run_suite ------------------------------------------
python -m umat_oti.validation.run_suite \
    --abaqus-command "${ABAQUS_CMD:-abaqus}" \
    --report "${RESULT_DIR}/run_suite.json" \
    --repo-root "${REPO_ROOT}" \
    > "${RESULT_DIR}/run_suite.stdout.json" \
    || echo "[$(date -Iseconds)] run_suite exited non-zero"

echo "[$(date -Iseconds)] ARC UMAT-OTI validation complete; artefacts in ${RESULT_DIR}"
