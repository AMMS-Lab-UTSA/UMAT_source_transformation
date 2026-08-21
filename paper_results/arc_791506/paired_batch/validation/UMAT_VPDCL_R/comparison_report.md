# Abaqus Stress Comparison

Status: `failed_execution`
Pass: `False`
Absolute tolerance: `1e-05`
Relative tolerance: `1e-07`

## Stress
Original: `[1.5, -2.220446049250313e-16, -2.220446049250313e-16, 6.776263578034403e-18, 0.0, 0.0]`
OTIS: `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]`
Max absolute difference: `1.5`
Max relative difference: `1.0`

## State Variables
Status: `failed`
Pass: `False`

## DDSDDE
Status: `failed`
Pass: `False`
Compared increments: `1`
Max absolute difference: `3000.0`
Max relative difference: `1.0`

## Constitutive Jacobians
Status: `not_requested`
Pass: `True`
Compared artifacts: `None`
Preview-only artifacts: `None`
Max absolute difference: `None`
Max relative difference: `None`

## Convergence
Status: `failed`
Pass: `False`

## Activation
Status: `failed`
Expected plasticity: `True`
Expected finite geometry: `False`
Pass: `False`

## Errors
- Original Abaqus validation job did not complete successfully (status=failed, returncode=1).
- Transformed Abaqus validation job did not complete successfully (status=failed, returncode=1).
