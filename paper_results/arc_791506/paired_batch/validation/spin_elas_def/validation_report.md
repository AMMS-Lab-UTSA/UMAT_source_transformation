# Abaqus Validation Report

Final pass: `True`
Status: `passed`
Abaqus command: `abaqus`
Original UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/UMATs/UMATs/ICP/spin/spin_elas_def.f`
Transformed UMAT: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/oti_transform/spin_elas_def/spin_elas_def_oti.f`
Validation directory: `/home/vfn333/softwarex_work/UMAT_source_transformation/paper_results/arc_791506/paired_batch/validation/spin_elas_def`

## Load Case
Mode: `single element plastic finite strain tension`
Validation NTENS: `6` (transformation ntens)
Step: `FINITE_PLASTIC_PROBE`
NLGEOM: `YES`
Expected plasticity: `True`

## Run Status
Original: `completed`
Transformed: `completed`
Extraction: `completed`
Comparison: `passed`

## Stress Comparison
Max absolute difference: `6.103515625e-05`
Max relative difference: `5.2171494189678924e-05`
Pass: `True`

## DDSDDE Validation
Status: `configured`
Method: `validation-only STATEV instrumentation`
STATEV slots: `7` to `42`

## DDSDDE Comparison
Status: `not_requested`
Compared increments: ``
Max absolute difference: ``
Max relative difference: ``
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
Expected finite geometry: `True`
Pass: `True`

## Warnings
- Compile script generated; compile smoke was not run.
