# Starter kit: transforming your own UMAT

This folder is for users who want to run UMAT-OTI on a UMAT of their own. It
explains the shortest route, how to write a JSON contract when you need one,
and which helper script to use at each step.

The reusable JSON templates and worked examples live at the repository root, in
`templates/`, `examples/` and `benchmarks/`. This folder holds the documents and
helper scripts that go with them.

## What is in this folder

- `README.md`: this page, the quickest path for a new user.
- `JSON_REFERENCE.md`: a field-by-field explanation of the compact JSON
  contract.
- `TROUBLESHOOTING.md`: common failures and what to check next.
- `scripts/scan_source.py`: inspect a raw UMAT source before writing a
  contract.
- `scripts/show_source_lines.py`: print the source with line numbers, so you can
  choose `replace` ranges.
- `scripts/check_config.py`: load-check a compact JSON contract and optionally
  write the expanded configuration.
- `scripts/run_from_json.py`: run the transform alone on one contract, without
  the full service.

Run every command below from the repository root, with the package installed
(`pip install -e .`) and Python 3.10 or newer.

## The shortest route: no contract at all

For the standard consistent tangent (`DDSDDE = dSTRESS/dDSTRAN`), you do not
need to write a contract. Give the source and the number of stress components:

```bash
umat-oti jacobian path/to/YOUR_UMAT.for --ntens 6 --out umat_oti_workspace/my_umat --compile
```

The transformer finds the existing tangent block itself and writes the
transformed UMAT, a drop-in `*_oti_combined.f90`, and the contract it used
(`jacobian_contract.json`), which you can edit and re-run. The GUI's
Constitutive Jacobian screen does the same thing (see
[docs/GUI.md](../docs/GUI.md)).

Write a contract by hand when you need to control what is replaced or promoted,
or when your UMAT calls helper routines defined in other files.

## Writing a contract

1. Inspect the UMAT source.

   ```bash
   python new_user_umat_starter/scripts/scan_source.py path/to/YOUR_UMAT.for
   python new_user_umat_starter/scripts/show_source_lines.py path/to/YOUR_UMAT.for --start 1 --end 220
   ```

2. Copy the minimal template and edit it.

   ```bash
   cp templates/new_umat_minimal_template.json json_files/my_new_umat.json
   ```

3. Fill in the required fields: `name`, `source`, `jacobian.seed`,
   `jacobian.output`, `jacobian.target`, `promote`, `replace`, `ntens` and
   `order`. `constant` and `real` are optional overrides; see
   [JSON_REFERENCE.md](JSON_REFERENCE.md).

4. Load-check the contract.

   ```bash
   python new_user_umat_starter/scripts/check_config.py --config json_files/my_new_umat.json
   ```

5. Optionally write the expanded internal configuration for inspection.

   ```bash
   python new_user_umat_starter/scripts/check_config.py \
     --config json_files/my_new_umat.json \
     --write-expanded umat_oti_workspace/my_new_umat.expanded.json
   ```

6. Transform it.

   ```bash
   umat-oti-config --config json_files/my_new_umat.json --out umat_oti_workspace/my_new_umat
   ```

   `umat-oti-config` runs the full transformation service: the same one the GUI
   and the batch driver use. It also resolves `dependency_roots`, writes the
   combined drop-in source and records every derivative request.

   Two lighter alternatives exist:

   ```bash
   python scripts/transform_from_json.py json_files/my_new_umat.json --out umat_oti_workspace/my_new_umat
   python new_user_umat_starter/scripts/run_from_json.py \
     --config json_files/my_new_umat.json \
     --out umat_oti_workspace/my_new_umat
   ```

   `scripts/transform_from_json.py` forwards to `umat-oti-config`.
   `run_from_json.py` calls the transform directly and prints a compact
   summary (anchor status, blockers, warnings, semantic checks). It does
   **not** resolve `dependency_roots`, so use `umat-oti-config` for a UMAT whose
   helper routines live in other files.

7. To use the GUI instead, start it and load the same file on tab
   **1. Load Config**:

   ```bash
   streamlit run scripts/app.py
   ```

   A contract uploaded through the browser has no location on disk, so its
   relative `source` path is resolved against the working directory and the
   repository root only. Load it from `json_files/` or `user_jsons/` instead,
   or use an absolute `source` path on the machine running the app.

### Running several contracts without arguments

`scripts/run_json_pipeline.py` transforms every contract under
`JSON_INPUT_PATH` (a file or a directory; `examples/` by default) into
`OUTPUT_DIRECTORY`. Edit those two names at the top of the script, then run:

```bash
python scripts/run_json_pipeline.py
```

The script only reads contracts you wrote; it never generates one. Paired
validation in Abaqus is off by default (`RUN_VALIDATION = False`). Switch it on
only on a machine with Abaqus configured; it then compares the transformed UMAT
with the original.

## Which file to start from

- `templates/new_umat_minimal_template.json`: a standard tangent-only UMAT.
- `templates/new_umat_constitutive_template.json`: only when you also need the
  advanced `constitutive_jacobians` or `helper_surfaces` sections.
- `examples/elastic_minimal.json`: the smallest real reference.
- `examples/hin_reference.json`: a larger real reference.
- `benchmarks/*.json`: the 19 benchmark contracts. All 19 transform with
  `umat-oti-config` (checked on 2026-09-18); `benchmarks/UMAT_PCO.json` shows
  how `dependency_roots` names a folder of helper routines.

## What each script is for

`scan_source.py`

- Prints the detected UMAT routines, candidate regions and a compact source
  summary.

`show_source_lines.py`

- Prints a source range with 1-based line numbers (`--start`, `--end`).
- Use it to find the old DDSDDE block for the `replace` list.

`check_config.py`

- Confirms the compact JSON can be loaded.
- Resolves the source path.
- Applies completed anchors where possible.
- Prints the anchor completion status and the key transform settings.

`run_from_json.py`

- Runs the transform on one contract and writes the generated source and the
  transform report into the chosen output directory (by default
  `umat_oti_workspace/new_user_runs/<contract-name>`).
- Exits 0 on success, 1 on failure, and 2 when the contract still needs
  completion (`needs_json_completion`).

## Next

- [JSON_REFERENCE.md](JSON_REFERENCE.md), for every contract field.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md), when a step fails.
- `examples/elastic_minimal.json`, the smallest working contract.
