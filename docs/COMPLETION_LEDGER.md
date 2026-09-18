# Completion ledger

One row per requirement of the master implementation directive (2026-09-18). The
only completed status is `PASS: reproduced from a clean installation`; anything
else is not completion. Implementation, Test and Reproduction command columns
must name real files and commands that exist on the final branches
(`integration/imqcam-2026-09-18` in both repositories).

Status vocabulary used while work is in progress (none of these count):
`NOT STARTED`, `IN PROGRESS (<worktree>)`, `IMPLEMENTED - not yet reproduced from clean install`,
`BLOCKED: <exact missing external resource>`.

| ID | Requirement | Repository | Implementation | Test | Reproduction command | Status |
| -- | ----------- | ---------- | -------------- | ---- | -------------------- | ------ |
| U-A1 | Install from a clean clone | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-A2 | Declare all required Python dependencies | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-A3 | Detect or document compiler requirements | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-A4 | CLI starts | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-A5 | GUI starts | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-A6 | Smoke test runs | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-A7 | Useful errors when optional external software (Abaqus, OTILib, ifort) is unavailable | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-A8 | Every operating system claimed in the documentation is supported or the claim is corrected | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B1 | Source analyzer identifies the UMAT entry routine | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B2 | identifies arguments | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B3 | identifies NTENS | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B4 | identifies NPROPS | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B5 | identifies NSTATV | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B6 | identifies stress variables | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B7 | identifies state variables | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B8 | identifies strain increments | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B9 | identifies parameter arrays | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B10 | identifies existing tangent blocks | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B11 | identifies local nonlinear solves | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B12 | identifies internal Jacobians | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B13 | identifies external dependencies | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B14 | identifies unsupported constructs | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B15 | Multiline statements, fixed form, free form, continuations, comments, literals and routine boundaries parse correctly | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-B16 | Unsupported source receives an explicit diagnostic and is never transformed incorrectly while appearing successful | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C1 | Compact transformation contract works | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C2 | Extended derivative schema works | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C3 | Contract supports material tangent | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C4 | supports local constitutive Jacobian | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C5 | supports parameter sensitivity | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C6 | supports state sensitivity | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C7 | supports higher derivative order | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C8 | supports parameter names and PROPS indices | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C9 | supports OTI directions | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C10 | supports material-point loading histories | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C11 | supports replacement ranges | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C12 | supports promoted variables | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-C13 | Contract validation identifies the exact missing or inconsistent field | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-D1 | Seeds all required DSTRAN directions | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-D2 | Preserves the original constitutive update | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-D3 | Promotes every variable required by the derivative chain | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-D4 | Disables or replaces the original tangent block | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-D5 | Extracts DDSDDE | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-D6 | Generates an Abaqus-compatible source | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-D7 | Verifies primal stress parity | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-D8 | Verifies the tangent against an independent reference | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-D9 | Works for linear and nonlinear materials | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-E1 | Local constitutive Jacobian: seeds the local iterate | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-E2 | preserves the residual evaluation | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-E3 | extracts the internal Jacobian | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-E4 | names the generated output clearly | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-E5 | verifies it against an analytic or finite-difference reference | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-F1 | Computes dSTRESS/dPROPS | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-F2 | named stress sensitivities | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-F3 | multiple parameter directions in one run | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-F4 | sensitivities across several increments | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-F5 | elastic and plastic sensitivities | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-F6 | verified nonzero derivatives for active parameters | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-G1 | Computes dSTATEV/dPROPS | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-G2 | state sensitivities across increments | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-G3 | correct state carryover | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-G4 | correct initialization | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-G5 | verified values against an independent reference | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-H1 | Higher order: allocates the requested OTI order | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-H2 | generates the correct direction map | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-H3 | extracts repeated and mixed derivatives | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-H4 | applies factorial recovery correctly | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-H5 | reports both coefficients and derivatives | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-H6 | verifies representative repeated and mixed terms | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I1 | Writes the transformed UMAT | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I2 | OTI module | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I3 | required support sources | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I4 | compile order | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I5 | combined Abaqus source | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I6 | derivative manifest | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I7 | transformation report | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I8 | run manifest | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I9 | verification output | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I10 | parameter- and state-sensitivity output | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-I11 | Combined source compiles through the documented Abaqus workflow (abaqus make / job with user=) on this machine | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-J1 | Configuration command (umat-oti-config) | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-J2 | Staged pipeline (umat-oti-pipeline) | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-J3 | Resume behaviour | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-J4 | Stage selection (--only) | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-J5 | Batch command (umat-oti-batch) | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-J6 | Reproduction command (python -m umat_oti.reproduce) | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-J7 | Primary GUI (streamlit run scripts/app.py) | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-J8 | Every secondary GUI still documented (unified_app, workbench) | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-J9 | CLI and GUI call the same application functions and produce equivalent artifacts | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-K1 | Supported UMAT corpus run: every source transforms or is rejected with an accurate named reason | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-K2 | No malformed transformation counted as success | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-K3 | Corpus not reduced and no difficult case removed | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-X1 | Example 1: linear elastic tangent | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-X2 | Example 2: nonlinear J2 tangent | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-X3 | Example 3: parameter sensitivities | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-X4 | Example 4: state sensitivities | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-X5 | Example 5: internal Jacobian / higher derivative / crystal plasticity (advanced verified model) | UMAT_source_transformation |  |  |  | NOT STARTED |
| U-X6 | Each example carries inputs, command, expected output, numerical verification, tolerance, machine-readable report, failure diagnostics, GUI equivalent | UMAT_source_transformation |  |  |  | NOT STARTED |
| R-A1 | Install from a clean clone | Residual_Assembler |  |  |  | NOT STARTED |
| R-A2 | Install GUI and YAML dependencies | Residual_Assembler |  |  |  | NOT STARTED |
| R-A3 | Initialize required source dependencies | Residual_Assembler |  |  |  | NOT STARTED |
| R-A4 | Install or correctly locate OTILib | Residual_Assembler |  |  |  | NOT STARTED |
| R-A5 | Detect the unrelated pyoti package | Residual_Assembler |  |  |  | NOT STARTED |
| R-A6 | CLI starts | Residual_Assembler |  |  |  | NOT STARTED |
| R-A7 | GUI starts | Residual_Assembler |  |  |  | NOT STARTED |
| R-A8 | Truthful backend statuses listed | Residual_Assembler |  |  |  | NOT STARTED |
| R-A9 | Smoke example runs | Residual_Assembler |  |  |  | NOT STARTED |
| R-B1 | Reads Abaqus input decks | Residual_Assembler |  |  |  | NOT STARTED |
| R-B2 | neutral JSON models | Residual_Assembler |  |  |  | NOT STARTED |
| R-B3 | nodes | Residual_Assembler |  |  |  | NOT STARTED |
| R-B4 | elements | Residual_Assembler |  |  |  | NOT STARTED |
| R-B5 | element sets | Residual_Assembler |  |  |  | NOT STARTED |
| R-B6 | node sets | Residual_Assembler |  |  |  | NOT STARTED |
| R-B7 | materials | Residual_Assembler |  |  |  | NOT STARTED |
| R-B8 | boundary conditions | Residual_Assembler |  |  |  | NOT STARTED |
| R-B9 | loads | Residual_Assembler |  |  |  | NOT STARTED |
| R-B10 | solution fields | Residual_Assembler |  |  |  | NOT STARTED |
| R-B11 | integration-point fields | Residual_Assembler |  |  |  | NOT STARTED |
| R-B12 | state variables | Residual_Assembler |  |  |  | NOT STARTED |
| R-B13 | reactions | Residual_Assembler |  |  |  | NOT STARTED |
| R-B14 | time and increment data | Residual_Assembler |  |  |  | NOT STARTED |
| R-B15 | No keyword that changes equilibrium is parsed and silently ignored (implement or precise diagnostic) | Residual_Assembler |  |  |  | NOT STARTED |
| R-C1 | C3D8 small strain: eight-node geometry | Residual_Assembler |  |  |  | NOT STARTED |
| R-C2 | 24 element DOFs | Residual_Assembler |  |  |  | NOT STARTED |
| R-C3 | shape functions | Residual_Assembler |  |  |  | NOT STARTED |
| R-C4 | natural derivatives | Residual_Assembler |  |  |  | NOT STARTED |
| R-C5 | spatial derivatives | Residual_Assembler |  |  |  | NOT STARTED |
| R-C6 | isoparametric Jacobian | Residual_Assembler |  |  |  | NOT STARTED |
| R-C7 | Gauss integration | Residual_Assembler |  |  |  | NOT STARTED |
| R-C8 | small-strain B matrix | Residual_Assembler |  |  |  | NOT STARTED |
| R-C9 | Abaqus Voigt order | Residual_Assembler |  |  |  | NOT STARTED |
| R-C10 | element internal force | Residual_Assembler |  |  |  | NOT STARTED |
| R-C11 | material tangent | Residual_Assembler |  |  |  | NOT STARTED |
| R-C12 | element stiffness | Residual_Assembler |  |  |  | NOT STARTED |
| R-C13 | global residual | Residual_Assembler |  |  |  | NOT STARTED |
| R-C14 | global tangent | Residual_Assembler |  |  |  | NOT STARTED |
| R-C15 | constraint partitioning | Residual_Assembler |  |  |  | NOT STARTED |
| R-C16 | free residual | Residual_Assembler |  |  |  | NOT STARTED |
| R-C17 | reactions | Residual_Assembler |  |  |  | NOT STARTED |
| R-C18 | multi-element assembly | Residual_Assembler |  |  |  | NOT STARTED |
| R-D1 | C3D8 finite strain: deformation gradient | Residual_Assembler |  |  |  | NOT STARTED |
| R-D2 | strain measure | Residual_Assembler |  |  |  | NOT STARTED |
| R-D3 | stress measure | Residual_Assembler |  |  |  | NOT STARTED |
| R-D4 | tangent measure | Residual_Assembler |  |  |  | NOT STARTED |
| R-D5 | volume measure | Residual_Assembler |  |  |  | NOT STARTED |
| R-D6 | state update | Residual_Assembler |  |  |  | NOT STARTED |
| R-D7 | rotation handling | Residual_Assembler |  |  |  | NOT STARTED |
| R-D8 | material and geometric contributions | Residual_Assembler |  |  |  | NOT STARTED |
| R-D9 | residual and tangent assembly | Residual_Assembler |  |  |  | NOT STARTED |
| R-D10 | Small-strain and finite-strain paths never mix incompatible measures | Residual_Assembler |  |  |  | NOT STARTED |
| R-E1 | Stress-driven assembly: one C3D8 | Residual_Assembler |  |  |  | NOT STARTED |
| R-E2 | multiple C3D8 elements | Residual_Assembler |  |  |  | NOT STARTED |
| R-E3 | all integration points | Residual_Assembler |  |  |  | NOT STARTED |
| R-E4 | global DOF mapping | Residual_Assembler |  |  |  | NOT STARTED |
| R-E5 | constrained and free DOFs | Residual_Assembler |  |  |  | NOT STARTED |
| R-E6 | reactions | Residual_Assembler |  |  |  | NOT STARTED |
| R-E7 | Verified against analytic and Abaqus references | Residual_Assembler |  |  |  | NOT STARTED |
| R-F1 | Material replay runs: replays increments in order | Residual_Assembler |  |  |  | NOT STARTED |
| R-F2 | reconstructs strain or deformation at each integration point | Residual_Assembler |  |  |  | NOT STARTED |
| R-F3 | passes previous state correctly | Residual_Assembler |  |  |  | NOT STARTED |
| R-F4 | calls the material provider | Residual_Assembler |  |  |  | NOT STARTED |
| R-F5 | updates stress and state | Residual_Assembler |  |  |  | NOT STARTED |
| R-F6 | obtains the tangent | Residual_Assembler |  |  |  | NOT STARTED |
| R-F7 | assembles residual and tangent | Residual_Assembler |  |  |  | NOT STARTED |
| R-F8 | supports multiple elements | Residual_Assembler |  |  |  | NOT STARTED |
| R-F9 | useful diagnostics for missing fields | Residual_Assembler |  |  |  | NOT STARTED |
| R-F10 | No backend claims readiness while material replay crashes | Residual_Assembler |  |  |  | NOT STARTED |
| R-G1 | OTI propagates through parameter seeding | Residual_Assembler |  |  |  | NOT STARTED |
| R-G2 | material evaluation | Residual_Assembler |  |  |  | NOT STARTED |
| R-G3 | state updates | Residual_Assembler |  |  |  | NOT STARTED |
| R-G4 | stress | Residual_Assembler |  |  |  | NOT STARTED |
| R-G5 | element residual | Residual_Assembler |  |  |  | NOT STARTED |
| R-G6 | global residual | Residual_Assembler |  |  |  | NOT STARTED |
| R-G7 | constraint application | Residual_Assembler |  |  |  | NOT STARTED |
| R-G8 | derivative extraction | Residual_Assembler |  |  |  | NOT STARTED |
| R-G9 | sensitivity right-hand sides | Residual_Assembler |  |  |  | NOT STARTED |
| R-G10 | reporting | Residual_Assembler |  |  |  | NOT STARTED |
| R-G11 | No derivative loss from float()/dtype=float/unsupported NumPy ops/premature real-part extraction/real-only zeros/unsupported linear algebra/object-array conversion/serialization before extraction | Residual_Assembler |  |  |  | NOT STARTED |
| R-G12 | Same scalar-generic kernels used for real and OTI values where practical | Residual_Assembler |  |  |  | NOT STARTED |
| R-H1 | T U^(p) = -R^(p) implemented and verified | Residual_Assembler |  |  |  | NOT STARTED |
| R-H2 | several parameters in one OTI run | Residual_Assembler |  |  |  | NOT STARTED |
| R-H3 | several derivative orders where advertised | Residual_Assembler |  |  |  | NOT STARTED |
| R-H4 | residual parameter derivatives | Residual_Assembler |  |  |  | NOT STARTED |
| R-H5 | state contributions | Residual_Assembler |  |  |  | NOT STARTED |
| R-H6 | solution sensitivities | Residual_Assembler |  |  |  | NOT STARTED |
| R-H7 | direction maps | Residual_Assembler |  |  |  | NOT STARTED |
| R-H8 | coefficients | Residual_Assembler |  |  |  | NOT STARTED |
| R-H9 | recovered derivatives | Residual_Assembler |  |  |  | NOT STARTED |
| R-H10 | parameter rankings | Residual_Assembler |  |  |  | NOT STARTED |
| R-H11 | full-field sensitivities | Residual_Assembler |  |  |  | NOT STARTED |
| R-I1 | Material providers: direct Python material | Residual_Assembler |  |  |  | NOT STARTED |
| R-I2 | compiled UMAT or material object | Residual_Assembler |  |  |  | NOT STARTED |
| R-I3 | OTI-enabled compiled provider | Residual_Assembler |  |  |  | NOT STARTED |
| R-I4 | private material-source workflow | Residual_Assembler |  |  |  | NOT STARTED |
| R-I5 | correct state exchange | Residual_Assembler |  |  |  | NOT STARTED |
| R-I6 | stress output | Residual_Assembler |  |  |  | NOT STARTED |
| R-I7 | tangent output | Residual_Assembler |  |  |  | NOT STARTED |
| R-I8 | derivative output | Residual_Assembler |  |  |  | NOT STARTED |
| R-I9 | error propagation | Residual_Assembler |  |  |  | NOT STARTED |
| R-J1 | resasm backends | Residual_Assembler |  |  |  | NOT STARTED |
| R-J2 | resasm modes | Residual_Assembler |  |  |  | NOT STARTED |
| R-J3 | resasm inspect | Residual_Assembler |  |  |  | NOT STARTED |
| R-J4 | resasm inspect-model | Residual_Assembler |  |  |  | NOT STARTED |
| R-J5 | resasm requirements | Residual_Assembler |  |  |  | NOT STARTED |
| R-J6 | resasm assemble | Residual_Assembler |  |  |  | NOT STARTED |
| R-J7 | resasm verify | Residual_Assembler |  |  |  | NOT STARTED |
| R-J8 | resasm sensitivity | Residual_Assembler |  |  |  | NOT STARTED |
| R-J9 | resasm init | Residual_Assembler |  |  |  | NOT STARTED |
| R-J10 | resasm init-assembly | Residual_Assembler |  |  |  | NOT STARTED |
| R-J11 | resasm check | Residual_Assembler |  |  |  | NOT STARTED |
| R-J12 | resasm run | Residual_Assembler |  |  |  | NOT STARTED |
| R-J13 | resasm report | Residual_Assembler |  |  |  | NOT STARTED |
| R-J14 | resasm doctor | Residual_Assembler |  |  |  | NOT STARTED |
| R-J15 | resasm template | Residual_Assembler |  |  |  | NOT STARTED |
| R-J16 | GUI executes the same code paths and never reports success where the CLI reports failure or blocked | Residual_Assembler |  |  |  | NOT STARTED |
| R-K1 | Reports distinguish: command executed | Residual_Assembler |  |  |  | NOT STARTED |
| R-K2 | residual assembled | Residual_Assembler |  |  |  | NOT STARTED |
| R-K3 | equilibrium checked | Residual_Assembler |  |  |  | NOT STARTED |
| R-K4 | equilibrium passed | Residual_Assembler |  |  |  | NOT STARTED |
| R-K5 | tangent available | Residual_Assembler |  |  |  | NOT STARTED |
| R-K6 | tangent verified | Residual_Assembler |  |  |  | NOT STARTED |
| R-K7 | derivative calculated | Residual_Assembler |  |  |  | NOT STARTED |
| R-K8 | derivative verified | Residual_Assembler |  |  |  | NOT STARTED |
| R-K9 | reference resolved | Residual_Assembler |  |  |  | NOT STARTED |
| R-K10 | Abaqus comparison available | Residual_Assembler |  |  |  | NOT STARTED |
| R-K11 | unsupported feature detected | Residual_Assembler |  |  |  | NOT STARTED |
| R-K12 | Public and private outputs separated | Residual_Assembler |  |  |  | NOT STARTED |
| R-X1 | Example 1: direct Python residual | Residual_Assembler |  |  |  | NOT STARTED |
| R-X2 | Example 2: higher-order black-box residual | Residual_Assembler |  |  |  | NOT STARTED |
| R-X3 | Example 3: stress-driven C3D8 | Residual_Assembler |  |  |  | NOT STARTED |
| R-X4 | Example 4: J2 C3D8 material replay with OTI sensitivities | Residual_Assembler |  |  |  | NOT STARTED |
| R-X5 | Example 5: finite-strain / cantilever / multi-element verified 3D model | Residual_Assembler |  |  |  | NOT STARTED |
| R-X6 | Each example carries inputs, command, expected output, numerical verification, tolerance, machine-readable report, failure diagnostics, GUI equivalent | Residual_Assembler |  |  |  | NOT STARTED |
| X-1 | Start with a real nonlinear UMAT | both |  |  |  | NOT STARTED |
| X-2 | Transform it with UMAT-OTI | both |  |  |  | NOT STARTED |
| X-3 | Generate constitutive tangents and parameter/state derivatives | both |  |  |  | NOT STARTED |
| X-4 | Compile the OTI-enabled material provider | both |  |  |  | NOT STARTED |
| X-5 | Run or load a converged C3D8 Abaqus analysis | both |  |  |  | NOT STARTED |
| X-6 | Export the required fields | both |  |  |  | NOT STARTED |
| X-7 | Load the model and fields in Residual Assembler | both |  |  |  | NOT STARTED |
| X-8 | Replay the material response | both |  |  |  | NOT STARTED |
| X-9 | Assemble the global residual and tangent | both |  |  |  | NOT STARTED |
| X-10 | Seed several material parameters | both |  |  |  | NOT STARTED |
| X-11 | Calculate dR/dp | both |  |  |  | NOT STARTED |
| X-12 | Solve for du/dp | both |  |  |  | NOT STARTED |
| X-13 | Recover full-field sensitivities | both |  |  |  | NOT STARTED |
| X-14 | Write public and private reports | both |  |  |  | NOT STARTED |
| X-15 | Compare against finite differences, an analytic reference, or Abaqus | both |  |  |  | NOT STARTED |
| X-16 | Run the same workflow from the GUI | both |  |  |  | NOT STARTED |
| X-17 | Reproduce it from a clean installation | both |  |  |  | NOT STARTED |
| X-18 | The IMQCAM Annual Meeting model (J2 cantilever 1,536 C3D8 / FCC cantilever 384 C3D8) recovered and reproduced, or a verified C3D8 nonlinear example on the identical software path | both |  |  |  | NOT STARTED |
| X-19 | One reproduction command (records both commits, environment, dependencies; transforms; compiles; loads model; assembles; sensitivities; validates; plots/tables; manifest; non-zero on failure) | both |  |  |  | NOT STARTED |
| T-1 | Unit tests | both |  |  |  | NOT STARTED |
| T-2 | Regression tests | both |  |  |  | NOT STARTED |
| T-3 | Public CLI tests | both |  |  |  | NOT STARTED |
| T-4 | GUI application tests | both |  |  |  | NOT STARTED |
| T-5 | Clean-install tests | both |  |  |  | NOT STARTED |
| T-6 | Analytic comparisons | both |  |  |  | NOT STARTED |
| T-7 | Finite-difference convergence sweeps | both |  |  |  | NOT STARTED |
| T-8 | Abaqus comparisons where available | both |  |  |  | NOT STARTED |
| T-9 | Cross-repository integration tests | both |  |  |  | NOT STARTED |
| T-10 | Example reproduction tests | both |  |  |  | NOT STARTED |
| T-11 | Every bug fixed during this work has a regression test | both |  |  |  | NOT STARTED |
| T-12 | No deleted failing tests, weakened tolerances, failures turned to warnings, broad exception hiding, skips to reach green, removed hard examples, metadata claiming support, mocked core math in integration tests, or self-comparison replacing independent validation | both |  |  |  | NOT STARTED |
| CI-1 | New empty environments created | both |  |  |  | NOT STARTED |
| CI-2 | Both repositories installed from their final branches | both |  |  |  | NOT STARTED |
| CI-3 | Only documented instructions followed | both |  |  |  | NOT STARTED |
| CI-4 | Every required example run | both |  |  |  | NOT STARTED |
| CI-5 | Both GUIs run | both |  |  |  | NOT STARTED |
| CI-6 | Entire test suites run | both |  |  |  | NOT STARTED |
| CI-7 | Cross-repository reproduction run | both |  |  |  | NOT STARTED |
| CI-8 | No undeclared local path required | both |  |  |  | NOT STARTED |
| CI-9 | No development artifact required | both |  |  |  | NOT STARTED |
| CI-10 | No result depends on cached output | both |  |  |  | NOT STARTED |
| CI-11 | Generated files can be deleted and recreated | both |  |  |  | NOT STARTED |

Rows: 274
