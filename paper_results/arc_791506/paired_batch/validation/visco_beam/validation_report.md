# Abaqus Validation Report

Final pass: `True`
Status: `passed`
Abaqus command: `abaqus`
Original UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/UMATs/UMATs/ICP/visco/visco_beam.f`
Transformed UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/oti_transform/visco_beam/visco_beam_oti.f`
Validation directory: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/validation/visco_beam`

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
Max absolute difference: `0.0`
Max relative difference: `0.0`
Pass: `True`

## DDSDDE Validation
Status: `configured`
Method: `validation-only STATEV instrumentation`
STATEV slots: `4` to `19`

## DDSDDE Comparison
Status: `passed`
Compared increments: `4`
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
Status: `passed`
Expected plasticity: `True`
Expected finite geometry: `False`
Pass: `True`

## Warnings
- Compile script generated; compile smoke was not run.
