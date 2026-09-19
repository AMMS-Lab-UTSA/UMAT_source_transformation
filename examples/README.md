# Worked examples

Six complete, runnable examples. Each one has its own folder with a README
that explains what it shows and why it matters, the mathematics in brief, the
exact commands, the equivalent GUI steps, the files it produces, the output we
measured, how that output is checked independently, the run time, and the
common problems.

Start with Example 1. It takes a few seconds and shows the central idea: the
derivative a UMAT needs is computed exactly from the code that already
exists.

| # | Example | What it shows | Abaqus? | One-line command (from the repository root) |
| --- | --- | --- | --- | --- |
| 1 | [Elastic tangent](01_elastic_tangent/README.md) | `DDSDDE` of a linear elastic UMAT from `umat-oti jacobian`, equal to the analytic isotropic stiffness to the last bit | No | `umat-oti jacobian parameter_sensitivity/models/m1_elastic/umat.for --ntens 6 --out umat_oti_workspace/examples/01_elastic --compile` |
| 2 | [J2 plasticity tangent](02_j2_plasticity_tangent/README.md) | The consistent tangent of J2 plasticity over elastic, plastic and unloading increments, against centred finite differences of the original with a step-size sweep | No | `umat-oti jacobian parameter_sensitivity/models/m3_j2/umat.for --ntens 6 --out umat_oti_workspace/examples/02_j2 --compile` |
| 3 | [J2 parameter sensitivities](03_j2_parameter_sensitivities/README.md) | `DSIGMA_DP` and `DSTATEV_DP` over a loading history, built into a compiled provider (`OTI_UMAT.obj`, `Mapping.json`, `REAL_UMAT.obj`, `transform_report.txt`); every entry judged against finite differences | No (optional hand-off needs Abaqus data) | `umat-oti-provider build parameter_sensitivity/models/m3_j2/contract_v2.json --out umat_oti_workspace/examples/03_j2/build --regular-object REAL_UMAT.obj` |
| 4 | [FCC crystal-plasticity provider](04_fcc_crystal_plasticity_provider/README.md) | The same for a 12-slip-system crystal with ten parameters and twelve state variables, verified on a tension-with-shear path | No | `python -m umat_oti.provider.collaborator examples/04_fcc_crystal_plasticity_provider/contract_tension_shear.json --out umat_oti_workspace/examples/04_fcc/package` |
| 5 | [Internal Newton Jacobian](05_internal_newton_jacobian/README.md) | The Jacobian of a UMAT's own local Newton solve, extracted by OTI, against finite differences and against the hand-coded Jacobian (which is 2.6 % off in the damage UMAT) | No | `python examples/05_internal_newton_jacobian/run.py --out umat_oti_workspace/examples/05_vpdco` |
| 6 | [Twenty-model sensitivity sweep](06_parameter_sensitivity_sweep/README.md) | Parameter sensitivities of all twenty bundled material models, with the full funnel from transform to verification | No | `python tools/run_parameter_sensitivity_sweep.py --work-dir "$PWD/umat_oti_workspace/examples/06_sweep/work" --results-dir "$PWD/umat_oti_workspace/examples/06_sweep/results"` |

Each README gives the full sequence of commands; the table shows only the
first or the main one. Examples 1 to 4 end with a small `run.py` in their
folder that prints a clear comparison.

## How to run them

1. Install UMAT-OTI and check that the smoke test passes
   ([docs/INSTALL.md](../docs/INSTALL.md)):

   ```bash
   python -m umat_oti.reproduce --profile smoke
   ```

2. Activate the virtual environment and stay in the **repository root**. All
   paths in the examples are relative to it.
3. Copy the commands from the example's README. They write under
   `umat_oti_workspace/examples/`, which git ignores. Any other directory
   works too.

Every example needs Python and `gfortran` only. None starts Abaqus. Where an
optional next step needs Abaqus (running the drop-in UMAT in a job, or handing
the provider to Residual_Assembler), the README gives the command and says
that it was not run.

All numbers in the READMEs were measured on 2026-09-18 on Linux with Python
3.11.7 and gfortran 9.4.0. Another compiler or platform can change the last
digits of the errors and the SHA-256 digests of the objects; the verdicts
should not change.

## The same work in the GUI

Examples 1 to 4 can also be done in the GUI (`streamlit run scripts/app.py`):
the **Constitutive Jacobian** tab for Examples 1 and 2, the **Parameter
Sensitivities** tab for Examples 3 and 4. Each README lists the clicks. The
GUI calls the same functions as the commands and writes byte-identical files.
Examples 5 and 6 are command-line only. See
[docs/GUI_GUIDE.md](../docs/GUI_GUIDE.md).

## Other files in this folder

| File | What it is |
| --- | --- |
| [elastic_minimal.json](elastic_minimal.json) | The smallest hand-written contract: the NTENS = 4 elastic UMAT. The GUI's **Start here** demo runs it. |
| [hin_reference.json](hin_reference.json) | A larger hand-written contract (viscoplastic damage UMAT, NTENS = 4). |
| [j2_actual_higher_order.json](j2_actual_higher_order.json), [code_imp_actual_higher_order.json](code_imp_actual_higher_order.json), [UMAT_PCL_actual_higher_order.json](UMAT_PCL_actual_higher_order.json), [UMAT_PCLK_actual_higher_order.json](UMAT_PCLK_actual_higher_order.json), [visco_imp_actual_higher_order.json](visco_imp_actual_higher_order.json) | Contracts for higher-order derivative studies of real UMATs. `umat-oti-config` and `umat-oti-pipeline` accept them ([docs/CLI_GUIDE.md](../docs/CLI_GUIDE.md)). |
| [verify_internal_jacobian.py](verify_internal_jacobian.py) | Part A of Example 5. |

To write a contract for your own UMAT, start with
[new_user_umat_starter/README.md](../new_user_umat_starter/README.md).
