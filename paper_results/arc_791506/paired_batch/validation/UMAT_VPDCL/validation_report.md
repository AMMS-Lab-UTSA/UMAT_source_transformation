# Abaqus Validation Report

Final pass: `True`
Status: `passed`
Abaqus command: `abaqus`
Original UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/UMATs/UMATs/ICP/UMAT_VPDCL.for`
Transformed UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/oti_transform/UMAT_VPDCL/UMAT_VPDCL_oti.for`
Validation directory: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/validation/UMAT_VPDCL`

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
Max absolute difference: `1.6093254089355469e-06`
Max relative difference: `1.6093254089355469e-06`
Pass: `True`

## DDSDDE Validation
Status: `configured`
Method: `validation-only STATEV instrumentation`
STATEV slots: `17` to `32`

## DDSDDE Comparison
Status: `passed`
Compared increments: `4`
Max absolute difference: `0.2370147705078125`
Max relative difference: `0.0011540414668875243`
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
