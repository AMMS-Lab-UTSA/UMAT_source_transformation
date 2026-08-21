# Abaqus Validation Report

Final pass: `False`
Status: `failed`
Abaqus command: `abaqus`
Original UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/UMATs/UMATs/ICP/UMAT_VPDCL_R.for`
Transformed UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/oti_transform/UMAT_VPDCL_R/UMAT_VPDCL_R_oti.for`
Validation directory: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/validation/UMAT_VPDCL_R`

## Load Case
Mode: `single element plastic tension`
Validation NTENS: `6` (transformation ntens)
Step: `PLASTIC_PROBE`
NLGEOM: `NO`
Expected plasticity: `True`

## Run Status
Original: `failed`
Transformed: `failed`
Extraction: `completed`
Comparison: `failed_execution`

## Stress Comparison
Max absolute difference: `1.5`
Max relative difference: `1.0`
Pass: `False`

## DDSDDE Validation
Status: `configured`
Method: `validation-only STATEV instrumentation`
STATEV slots: `18` to `53`

## DDSDDE Comparison
Status: `failed`
Compared increments: `1`
Max absolute difference: `3000.0`
Max relative difference: `1.0`
Pass: `False`

## State Variables
Status: `failed`
Pass: `False`

## Convergence
Status: `failed`
Pass: `False`

## Activation
Status: `failed`
Expected plasticity: `True`
Expected finite geometry: `False`
Pass: `False`

## Warnings
- Compile script generated; compile smoke was not run.

## Errors
- Original Abaqus validation job did not complete successfully (status=failed, returncode=1).
- Transformed Abaqus validation job did not complete successfully (status=failed, returncode=1).
