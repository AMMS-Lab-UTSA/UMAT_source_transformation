# Abaqus Validation Report

Final pass: `True`
Status: `passed`
Abaqus command: `abaqus`
Original UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/UMATs/UMATs/ICP/UMAT_NKH_1.02.for`
Transformed UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/oti_transform/UMAT_NKH_1.02/UMAT_NKH_1.02_oti.for`
Validation directory: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/validation/UMAT_NKH_1.02`

## Load Case
Mode: `single element plastic tension`
Validation NTENS: `4` (transformation ntens)
Step: `PLASTIC_PROBE`
NLGEOM: `NO`
Expected plasticity: `True`

## Run Status
Original: `completed`
Transformed: `completed`
Extraction: `completed`
Comparison: `passed`

## Stress Comparison
Max absolute difference: `7.795635610818863e-06`
Max relative difference: `7.795635610818863e-06`
Pass: `True`

## DDSDDE Validation
Status: `configured`
Method: `validation-only STATEV instrumentation`
STATEV slots: `17` to `32`

## DDSDDE Comparison
Status: `passed`
Compared increments: `4`
Max absolute difference: `0.72344970703125`
Max relative difference: `0.0021311044913665477`
Pass: `True`

## State Variables
Status: `passed`
Pass: `True`

## Convergence
Status: `passed`
Pass: `True`

## Activation
Status: `passed`
Expected plasticity: `True`
Expected finite geometry: `False`
Pass: `True`

## Warnings
- Compile script generated; compile smoke was not run.
