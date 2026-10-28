# Intake: `umat_j2_voce.f`

Source `umat_j2_voce.f` (sha256 `06902c554f58121c`), no deck given, searched in `input`.

Each item is **FOUND** (the file says it), **INFERRED** (read from the code by a rule), **DEFAULT** (nothing says it; the default is stated) or **MISSING** (nothing says it and there is no honest default).

| Status | Item | What was found | Where |
|---|---|---|---|
| FOUND | Material routine | UMAT at line 38 | `umat_j2_voce.f:38` `SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,` |
| MISSING | Deck that feeds this routine | none found (no deck with a *USER MATERIAL block was found next to the file) |  |
| INFERRED | Stress components (NTENS) | 6 (read from what the routine does with its stress tensor) | `umat_j2_voce.f:75` `DO I = 4, 6` |
| INFERRED | Element / formulation | C3D8 (three-dimensional continuum) | `umat_j2_voce.f:75` `DO I = 4, 6` |
| INFERRED | Geometric nonlinearity (NLGEOM) | no: small strain (the routine never reads DFGRD0/DFGRD1; no deck says otherwise) |  |
| INFERRED | State variables (NSTATV / *DEPVAR) | 1 (the highest STATEV the routine names) | `umat_j2_voce.f:68` `EPN = STATEV(1)` |
| INFERRED | Constants (PROPS count) | 6 (the highest PROPS the routine names (all of them, by literal subscript)) | `umat_j2_voce.f:62` `BSAT = PROPS(6)` |
| FOUND | Constants (names) | PROPS(1)=YMOD, PROPS(2)=PNU, PROPS(3)=SIGY0, PROPS(4)=HLIN, PROPS(5)=QSAT, PROPS(6)=BSAT | `umat_j2_voce.f:57` `YMOD = PROPS(1)`<br>`umat_j2_voce.f:58` `PNU = PROPS(2)` |
| MISSING | Constant values | not found |  |
| DEFAULT | Loading | a generated path that makes the material do something, in unit time increments (chosen by the program, not by you; zero initial stress and state) |  |
| FOUND | Reads temperature (TEMP/DTEMP) | no |  |
| FOUND | Reads position (COORDS) | no |  |
| FOUND | Reads element number (NOEL) | no |  |
| FOUND | Reads field variables (PREDEF/DPRED) | no |  |
| FOUND | Helper routines it calls | none needed |  |
| FOUND | Files it INCLUDEs | none needed (ABA_PARAM.INC is supplied by the solver) |  |
| FOUND | Modules it USEs | none needed |  |
| DEFAULT | What to differentiate | stress and tangent with respect to all 6 constant(s) the routine reads (constants that are switches or flags are not worth differentiating; say so if one is) |  |

## What I need from you

- I could not find the numbers this material needs: the values of its 6 constants: YMOD, PNU, SIGY0, HLIN, QSAT, BSAT (read from the material definition), in the order the routine reads them.  
  *If you say nothing:* The run cannot go on, and the constants are never guessed or filled in for you. Put an Abaqus input file with a *USER MATERIAL block next to the UMAT, or type the values into a material file and pass it with --material-config FILE (if the input file lives elsewhere, use --material-discovery-root FOLDER).

## Assumed (defaults you can change)

- **Loading**: a generated path that makes the material do something, in unit time increments
- **What to differentiate**: stress and tangent with respect to all 6 constant(s) the routine reads
