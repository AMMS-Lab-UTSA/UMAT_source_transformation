# Abaqus Validation Report

Final pass: `True`
Status: `passed`
Abaqus command: `abaqus`
Original UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/UMATs/UMATs/ICP/elasticity/elastic.f`
Transformed UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/oti_transform/elastic/elastic_oti.f`
Validation directory: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/validation/elastic`

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
STATEV slots: `2` to `17`

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
