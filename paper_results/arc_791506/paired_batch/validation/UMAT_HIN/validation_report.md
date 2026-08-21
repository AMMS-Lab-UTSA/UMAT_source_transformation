# Abaqus Validation Report

Final pass: `True`
Status: `passed`
Abaqus command: `abaqus`
Original UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/UMATs/UMATs/ICP/UMAT_HIN.for`
Transformed UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/oti_transform/UMAT_HIN/UMAT_HIN_oti.for`
Validation directory: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/validation/UMAT_HIN`

## Load Case
Mode: `single element tension`
Validation NTENS: `4` (transformation ntens)
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
STATEV slots: `11` to `26`

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
