# Abaqus Validation Report

Final pass: `True`
Status: `passed`
Abaqus command: `abaqus`
Original UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/UMATs/UMATs/ICP/UMAT_ECL_TEMP.for`
Transformed UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/oti_transform/UMAT_ECL_TEMP/UMAT_ECL_TEMP_oti.for`
Validation directory: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/validation/UMAT_ECL_TEMP`

## Load Case
Mode: `single element tension`
Validation NTENS: `6` (transformation ntens)
Step: `SMALL_STRAIN`
NLGEOM: `NO`
Expected plasticity: `False`

## Run Status
Original: `completed`
Transformed: `completed`
Extraction: `completed`
Comparison: `passed`

## Stress Comparison
Max absolute difference: `0.0`
Max relative difference: `0.0`
Pass: `True`

## DDSDDE Validation
Status: `configured`
Method: `validation-only STATEV instrumentation`
STATEV slots: `13` to `48`

## DDSDDE Comparison
Status: `passed`
Compared increments: `1`
Max absolute difference: `0.0`
Max relative difference: `0.0`
Pass: `True`

## State Variables
Status: `passed`
Pass: `True`

## Convergence
Status: `passed`
Pass: `True`

## Activation
Status: `not_required`
Expected plasticity: `False`
Expected finite geometry: `False`
Pass: `True`

## Warnings
- Compile script generated; compile smoke was not run.
