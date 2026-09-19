# Installing UMAT-OTI

This guide takes you from a clean Linux machine to a working installation in
about five minutes, and shows how to check that it works. Every command and
every number on this page was run and measured on 2026-09-18.

## 1. Requirements

| Requirement | Needed for | Tested version |
| --- | --- | --- |
| Linux (x86-64) | everything | Ubuntu 20.04.6 LTS |
| Python 3.10 or newer, with `venv` | everything | 3.11.7 |
| `gfortran` | compiling and checking the generated Fortran (almost every workflow) | GNU Fortran 9.4.0 |
| `make` | the parameter-sensitivity and internal-Jacobian checks | GNU Make 4.2.1 |
| `git` | cloning the repository | 2.25.1 |
| Abaqus (optional) | running jobs in Abaqus: paired validation, exporting an ODB, `--abaqus-toolchain` | Abaqus 2021.HF5 |
| Intel Fortran `ifort` (optional) | compiling user subroutines inside Abaqus (`abaqus make`) | ifort 2023.2.1 |

Abaqus and `ifort` are **not** needed to transform a UMAT, to build and
verify a compiled provider, or to run any of the worked examples in
[examples/](../examples/README.md).

Windows and macOS are not tested. On Windows, use WSL 2 with Ubuntu and follow
the Linux steps inside it (see [Troubleshooting](#9-troubleshooting)).

## 2. Install the system packages

On Ubuntu or Debian:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip gfortran git make
```

Check that the compiler is found:

```bash
gfortran --version
```

## 3. Get the source

```bash
git clone https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation.git
cd UMAT_source_transformation
```

All later commands run from this folder, the **repository root**.

## 4. Create a virtual environment and install

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

- `-e` installs in editable mode, so the package runs from your checkout and
  the examples, models and scripts of the repository are all available.
- `[test]` adds `pytest` and the few packages the test suite needs. The core
  dependencies (NumPy, pandas, Streamlit, SymPy) are always installed.
- Other extras: `[paper]` (plots and documents for the publication
  artefacts) and `[screenshots]` (browser tests of the GUI; also run
  `playwright install chromium`).

Measured on 2026-09-18 in a new virtual environment: creating it took 2.8 s
and `pip install -e ".[test]"` 23.9 s (with packages already in pip's cache;
a first download takes longer). `python -m pip check` reported
`No broken requirements found.`

Activate the environment (`. .venv/bin/activate`) in every new terminal.

## 5. Run the smoke check

```bash
python -m umat_oti.reproduce --profile smoke
```

It transforms one J2-plasticity UMAT, compiles it, compiles the original
UMAT separately, runs both along a strain path, and checks that the
derivatives agree with centred finite differences of the original. Measured
output on 2026-09-18 (6.6 s):

```text
reproduce: profile=smoke out=<repository>/reproduce/smoke
  [                         succeeded] import_package (0.2s)
  [                         succeeded] material_point_smoke (5.3s)

wrote <repository>/reproduce/smoke/reproduction_summary.md
```

The exit code is 0. `reproduce/smoke/reproduction_summary.md` ends with
`2 succeeded, 0 failed, 0 unavailable for a stated external reason.` The
folder also holds `run_manifest.json`, `environment.json`,
`claim_matrix.json` and `artifact_checksums.sha256`.

Exit codes of `python -m umat_oti.reproduce`: `0` every step succeeded or was
unavailable for a stated external reason, `1` a step that should have worked
failed, `2` the profile could not start.

## 6. Verify the installation

```bash
umat-oti --help
umat-oti-provider --help
python -c "import umat_oti; print(umat_oti.__file__)"
```

- The first two print their usage (`usage: umat-oti [-h]
  {transform,config,jacobian} ...` and `usage: umat-oti-provider [-h]
  {build} ...`).
- The last one prints the path of `src/umat_oti/__init__.py` **inside your
  checkout**. If it points somewhere else, another copy of the package is
  shadowing yours; see [Troubleshooting](#9-troubleshooting).

Then run Example 1, which takes a few seconds:

```bash
umat-oti jacobian parameter_sensitivity/models/m1_elastic/umat.for \
    --ntens 6 --out umat_oti_workspace/examples/01_elastic --compile
python examples/01_elastic_tangent/run.py --jacobian-dir umat_oti_workspace/examples/01_elastic
```

The last line must read
`RESULT: PASS (OTI tangent equals the analytic stiffness to 1e-12)`.

Optional, longer checks:

```bash
python -m pytest -q tests/gui/test_developer_screens.py   # the two main GUI screens, about 2 min
python -m pytest -q                                        # the offline test suite
```

On 2026-09-18 the first command reported `17 passed in 121.21s`. The full
offline suite takes considerably longer; a skipped test names the missing
prerequisite, and a skip is not a pass.

To start the GUI:

```bash
streamlit run scripts/app.py
```

Streamlit prints a local URL (by default `http://localhost:8501`); open it in
a browser. See [GUI_GUIDE.md](GUI_GUIDE.md).

## 7. Install the companion Residual_Assembler (optional)

[Residual_Assembler](https://github.com/AMMS-Lab-UTSA/Residual_Assembler)
consumes the compiled material provider that UMAT-OTI builds
(`OTI_UMAT.obj` + `Mapping.json`) together with a converged Abaqus analysis,
and computes parameter sensitivities of the finite-element solution. Install
it next to UMAT-OTI, into the same virtual environment:

```bash
cd ..
git clone https://github.com/AMMS-Lab-UTSA/Residual_Assembler.git
python -m pip install -e "./Residual_Assembler[gui,yaml,test]"
resasm --help
cd UMAT_source_transformation
```

Measured on 2026-09-18 in the environment of step 4: the install took 6.3 s,
`python -m pip check` found no broken requirements, and `resasm --help`
printed its usage (`usage: resasm [-h] [--config CONFIG] {replay,request,
history,...}`) with exit code 0.

Use the `gui,yaml,test` extras shown. Residual_Assembler's own documentation
describes its commands and examples.

## 8. Optional: Abaqus and the Intel compiler

Abaqus is used only by these paths:

- the paired validation, which runs the original and the transformed UMAT in
  the same Abaqus job and compares them (GUI tabs **3. Validate**, **4.
  Constitutive Jacobians**, **5. Report**, and `umat-oti-batch --validate`);
- `umat-oti-provider build ... --abaqus-toolchain`, which compiles
  `REAL_UMAT.obj` with `abaqus make` (the Abaqus site compiler, `ifort` on
  Linux);
- exporting an ODB for Residual_Assembler.

UMAT-OTI looks for the command `abaqus` on `PATH`. To use another name, set
`ABAQUS_COMMAND` for the reproduction profiles, pass `--abaqus` to
`umat-oti-provider build`, or edit the **Abaqus command** field on the GUI's
**3. Validate** tab. To check what UMAT-OTI sees, run the `abaqus` profile: it
runs the smoke check and then reports whether Abaqus is usable (it asks
Abaqus for its release and for a licence; it does not start an analysis).

```bash
python -m umat_oti.reproduce --profile abaqus
```

A missing Abaqus is reported by name, never as a pass. Measured on 2026-09-18
with `ABAQUS_COMMAND=abaqus-not-installed`:

```text
  [                         succeeded] import_package (0.1s)
  [                         succeeded] material_point_smoke (5.4s)
  [    blocked_by_external_dependency] abaqus_paired_validation (0.0s)
```

and the summary names the reason: `abaqus-not-installed is not on PATH.`

## 9. Troubleshooting

| Problem | What you see | Fix |
| --- | --- | --- |
| `gfortran` is not installed | The smoke check prints `blocked_by_external_dependency` for `material_point_smoke`, with the reason `gfortran is not on PATH; no Fortran build or execution is possible` (exit code 0: nothing failed, but nothing was verified). `umat-oti jacobian ... --compile` reports `"compilation": {"status": "compiler_unavailable"}` and exits with 1. | `sudo apt install gfortran`, then open a new terminal. |
| Abaqus is not installed | The `abaqus` profile names it (`abaqus is not on PATH`), and the GUI shows `` `abaqus` not on PATH ``. | Nothing to do unless you need an Abaqus path (section 8). |
| Python is too old | `pip` refuses: `requires a different Python` (the package requires Python >= 3.10). | Install Python 3.10 or newer and create the virtual environment with it, for example `python3.11 -m venv .venv`. |
| `umat-oti: command not found` | The shell does not see the console scripts. | Activate the environment: `. .venv/bin/activate`. Every command also works as a module: `python -m umat_oti.cli ...`, `python -m umat_oti.provider ...`, `python -m streamlit run scripts/app.py`. |
| The wrong copy of `umat_oti` is imported | `python -c "import umat_oti; print(umat_oti.__file__)"` points outside your checkout. | An older installation or a `PYTHONPATH` entry shadows it. Run `unset PYTHONPATH`, or reinstall with `python -m pip install -e ".[test]"` in this checkout. |
| Someone suggests `pip install pyoti` | | **Do not install the PyPI package `pyoti`.** It is an unrelated project with the same name. UMAT-OTI generates its own OTI Fortran modules and needs no OTI Python package. Only some Residual_Assembler examples use the Python build of OTILib, which is built from its own source and is not on PyPI. |
| Windows | Fortran builds or paths fail in PowerShell or `cmd`. | Use WSL 2: `wsl --install -d Ubuntu`, then follow sections 2 to 6 inside Ubuntu. Keep the checkout in the Linux file system (for example `~/`), not under `/mnt/c`, for speed. Running Abaqus from inside WSL is not covered by this guide. |
| `make: command not found` in Examples 5 and 6 | A check step fails while building the OTI probe. | `sudo apt install make`. |
| The GUI port is busy | Streamlit says the port is in use. | `streamlit run scripts/app.py --server.port 8502`. |

Still stuck? Every command writes a machine-readable record of what it did
(`run_manifest.json`, `transform_report.txt`, `verification.json`). Open an
issue at <https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation/issues>
and attach that record.

## Next steps

- [examples/README.md](../examples/README.md): six worked examples.
- [CLI_GUIDE.md](CLI_GUIDE.md): every command, its options and exit codes.
- [GUI_GUIDE.md](GUI_GUIDE.md): the graphical interface, tab by tab.
