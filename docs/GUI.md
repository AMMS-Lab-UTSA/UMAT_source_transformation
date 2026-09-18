# The UMAT-OTI GUI

The graphical interface is one Streamlit application. Its first three tabs are
the developer's side of the IMQCAM presentation workflow: **Start here**,
**Constitutive Jacobian** (slides 16 and 40) and **Parameter Sensitivities**
(slides 17 and 41). The numbered tabs after them (**1. Load Config** to
**6. Corpus**) are the contract-driven console described in the README.

Every button calls the same Python function as a command, so a screen can
never compute something the command line would not. Each section below
gives the matching command.

## Launch

From the repository root, with the package installed (`pip install -e ".[gui]"`)
and `gfortran` on `PATH`:

```bash
streamlit run scripts/app.py
```

Headless on a chosen port (this is how the browser tests start it):

```bash
streamlit run scripts/app.py --server.headless true --server.port 8501
```

The two presentation screens write under `umat_oti_workspace/presentation/`
(git-ignored). Set `UMAT_OTI_GUI_WORKSPACE` to write somewhere else. Each click
gets a new directory, so an earlier result is never overwritten.

## Constitutive Jacobian (slides 16 and 40)

![Constitutive Jacobian screen after Transform on the m3_j2 UMAT](screenshots/umat_constitutive_jacobian.png)

"Load the UMAT and set the amount of stress components. Differentiate STRESS
with respect to DSTRAN, and write into DDSDDE. The Jacobian block is found for
you. Click Transform."

| Field | What it is |
| --- | --- |
| Fortran source file (.for) | an upload, or a path on this machine |
| Number of stress components (NTENS) | 3, 4 or 6. The screen suggests a value from the source; the user decides |
| differentiate with respect to / of the output / write into | `DSTRAN` / `STRESS` / `DDSDDE` by default |
| Tangent block (detected automatically) | read-only: the lines the transformer will replace and the variables it will carry through the derivative |

**What it calls.** `umat_oti.services.jacobian_request.run_jacobian_transform`
([source](../src/umat_oti/services/jacobian_request.py)). It writes a compact
contract with `replace` left empty, which makes the transformer's own anchor
inference (`merge_completed_anchors_into_config` in
`src/umat_oti/core/transformation_anchors.py`) find the DDSDDE block. It then
runs `umat_oti.services.transformation.run_transformation`, the service behind
every other front end. The preview shown before the click comes from the same
two steps, run without writing anything.

**What it writes.** A fresh directory `jacobian/<source>-XXXX/` holding
`jacobian_contract.json` (the four fields as a contract), the transformed
source (for the J2 model, `umat_oti.for`), the drop-in `umat_oti_combined.f90`
(the transformed routine together with every OTI module it needs), the OTI
modules, `derivative_manifest.json`, and `transform_report.txt`/`.json`. You
can download the transformed UMAT, the drop-in, the report and the contract.

**The same thing from a terminal.** The screen prints this command:

```bash
umat-oti jacobian path/to/umat.for --ntens 6 --out out_dir
# equivalently, from the contract the screen wrote:
umat-oti-config --config out_dir/jacobian_contract.json --out out_dir2
```

**Measured (2026-09-18).**

- m3_j2 (`parameter_sensitivity/models/m3_j2/umat.for`, NTENS 6): the screen
  finds the old tangent at lines 86-108 and carries DEQPL, EQPLAS, FLOW,
  SHYDRO, SMISES, STATEV, STRESS, SYIEL0 and SYIELD. It reports 0 blockers,
  0 warnings and 21 of 21 structural checks passed. The downloaded
  `umat_oti.for` and the drop-in are byte-identical to the output of
  `umat-oti jacobian` and of `umat-oti-config` with the written contract. The
  drop-in's DDSDDE was checked against centred finite differences of the
  separately compiled ORIGINAL routine at all 7 increments of the provider
  check path (elastic, plastic and unloading increments), at E=200000,
  nu=0.3, SIGY0=250, H=2000. Primal stress differed by at most 3.6e-15
  (stress scale 684). Scaled tangent errors were 3.25e-8, 3.25e-10 and
  2.95e-11 at strain steps 1e-6, 1e-7 and 1e-8.
- The elastic example (`UMATs/UMATs/ICP/elasticity/elastic.f`, NTENS 4): the
  screen finds lines 83-87. The transformed `elastic_oti.f` is byte-identical
  to what the hand-written `examples/elastic_minimal.json` produces. The
  tangent's scaled errors against FD of the original were at most 2.8e-12.

## Parameter Sensitivities (slides 17 and 41)

![Parameter Sensitivities after Build for m3_j2 at the slide-41 values](screenshots/umat_parameter_sensitivities_j2.png)

"Take the UMAT provided by the source transform. List the parameters with
their index and value. Tick stress and state derivatives as output requests.
Then Build and the OTI-enabled UMAT is automatically generated."

| Field | What it is |
| --- | --- |
| use the UMAT from the Constitutive Jacobian screen | ticked when that screen has a source; otherwise upload a file or give a path |
| Number of state variables (NSTATV) | the routine's physical state size |
| parameter / PROPS index / value | one row per parameter. The table starts empty. A source that is byte-identical to a shipped model (`parameter_sensitivity/models/*`) gets a button that fills the table from that model's contract |
| stress (DSIGMA_DP), state (DSTATEV_DP, auto) | the provider's derivative requests. DSIGMA_DP cannot be switched off because it is what the provider builds. DSTATEV_DP is always carried when NSTATV > 0 |
| Options | model name (names the canonical `umat_<name>_oti.obj`); verification on/off; require the J2 branch sequence on the check path |

NPROPS is the largest PROPS index in the table, and every slot up to it must
have a row. The independent check replays the original routine, and that needs
a value in every slot.

**What it calls.** `umat_oti.provider.collaborator.package`
([source](../src/umat_oti/provider/collaborator.py)) runs two existing commands
as subprocesses and keeps their exit codes:

```bash
python -m umat_oti.provider build contract_v2.json --out out/build --regular-object REAL_UMAT.obj
python -m umat_oti.validation.parameter_sensitivity_provider contract_v2.json --out out/verification
```

The first is `umat-oti-provider build`. The second is the provider's
independent check: primal parity against the separately compiled ORIGINAL,
then centred finite differences of the ORIGINAL over a step sweep (see
[PROVIDER.md](PROVIDER.md)). The verifier builds its own copy of the object,
and builds embed their build-directory paths, so the two objects are not
byte-identical. The package therefore evaluates both objects through the
verifier's own ABI client on the check path and requires bit-identical
arrays. It also checks that the generated Fortran sources are identical.

**What it writes.** A fresh directory `provider/<model>-XXXX/` with the staged
model (`<model>/umat.for`, `contract_v2.json`), `out/build/` (the provider's
canonical `umat_<model>_oti.obj`, `.json`, `REAL_UMAT.obj`, and the retained
`build-*` sources), `out/verification/verification.json`, `out/logs/`,
`out/package.json`, and the four files the presentation's developer hands
over, in `out/collaborator/`:

| File | Content |
| --- | --- |
| `REAL_UMAT.obj` | the ORIGINAL UMAT compiled unchanged: the same object the provider bundles, from the same compiler, flags and source |
| `OTI_UMAT.obj` | the provider: the original routine plus the differentiated one (`umat_oti_eval_`, `umat_oti_march_`) |
| `Mapping.json` | the provider's generated contract, unchanged. It records both objects' SHA-256 (`object.sha256_full`, `regular_object.sha256_full`) |
| `transform_report.txt` | the build and verification commands with their exit codes, the parameter table, primal parity, every FD step's scaled error, the plateau, and the tie between the shipped and the verified object |

All four can be downloaded. The source is not among them. The same package
from a terminal:

```bash
python -m umat_oti.provider.collaborator model_dir/contract_v2.json --out out --j2-branches
```

Exit code 0 means built and verified, 1 means built but not verified, and
2 means not built.

**Measured (2026-09-18).**

- m3_j2 with slide 41's table (E=200000, nu=0.3, SIGY0=250, H=2000, NSTATV 1,
  J2 branch sequence required): build exit 0, verification exit 0. The check
  path was elastic, elastic, plastic, plastic, elastic, plastic, elastic.
  Primal parity: stress 3.6e-15, state 2.2e-19. Scaled errors at the finest
  step: DSIGMA_DP 2.65e-9, DSTATEV_DP 1.20e-9, DDSDDE 2.95e-11 (tolerance
  2e-6, every step of the sweep checked, 2,659 comparisons). The shipped object
  returned bit-identical arrays to the verified build. The slide shows 5.98e-11
  and 1.37e-10. Those numbers are not reproduced here: this check measures a
  different quantity, the scaled max error at the finest step of a three-step
  sweep.
- m6_fcc with slide 17's ten parameters (C11=168000, C12=121000, C44=75000,
  g0=13, gsat=55, h0=800, a=2, q=1.4, gd0=0.001, m=0.05; NSTATV 12): **build
  exit 0**. The Mapping.json lists the ten parameters with their PROPS indices
  1-10. **Verification exit 2**: "provider/reference contains nonfinite
  values". The verifier's check path is the fixed J2 path, with strain
  increments up to 3.2e-3 per unit time. That path drives this explicit,
  sub-stepped, rate-dependent crystal update to non-finite values in the
  ORIGINAL routine too. The screen reports the build as not verified and
  shows the diagnostic.

![Parameter Sensitivities after Build for the ten-parameter FCC model](screenshots/umat_parameter_sensitivities_fcc.png)

## Tests

| Test | What it drives | Run |
| --- | --- | --- |
| `tests/gui/test_imqcam_developer_screens.py` | both screens through `streamlit.testing` (AppTest): GUI output against `umat-oti jacobian` and `umat-oti-config`, the elastic output against the curated example, the downloaded tangent against FD of the original, the J2 and FCC builds against the verifier CLI, and the table and tick rules | the offline suite |
| `tests/test_provider_regular_object.py` | `umat-oti-provider build --regular-object`: the object is the bundled original; its hash is in the contract; linked alone it replays the original bit for bit | the offline suite |
| `tests/gui/test_imqcam_developer_screens_browser.py` | the same flows in headless Chromium, as the slides describe them: upload, type the table, tick, click, download. Compares with the CLI and writes the screenshots above | `python -m pytest -m gui tests/gui` |

Browser tests start their own Streamlit server and stop that one process id.
They are deselected unless `-m gui` is given (see
[tests/gui/conftest.py](../tests/gui/conftest.py)).

## Limits

- The provider screen builds what the provider supports: three-dimensional
  (NTENS 6), small-strain, first-order STRESS-with-respect-to-PROPS providers
  ([PROVIDER.md](PROVIDER.md)).
- Its independent check uses the provider verifier's fixed seven-increment
  path. A material that cannot integrate that path (m6_fcc) is built but not
  verified.
- `REAL_UMAT.obj` is compiled with the provider's compiler, gfortran on this
  machine. Abaqus on Linux normally compiles user subroutines with its own
  Intel compiler. Linking a gfortran object into an Abaqus job was not tested.
- Objects embed absolute build paths in their bounds-check messages, so a
  rebuild does not reproduce them byte for byte. A shared object also reveals
  the developer's directory names, but not the source.
