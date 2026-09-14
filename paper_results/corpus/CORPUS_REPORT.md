# Corpus verification report

391 acquired entries, of which 341 present a UMAT interface to Abaqus.

**41 fully verified.**

* 41 of 391 acquired entries -- 10.5% of acquired entries
* 41 of 341 entries presenting a UMAT interface -- 12.0% of entries presenting a UMAT interface. This is NOT the same as the adequately specified genuine UMATs: it still counts files with no material constants published, files whose modules were never published beside them, and files whose UMAT body is empty. `paper_results/corpus/CORPUS_VERIFICATION.md` keeps those two denominators apart and names both.

Only `fully_verified` counts. It means the source transformed and
compiled, Abaqus ran the ORIGINAL, Abaqus ran the CONVERTED build
on the same deck, their stress and state histories agreed over the
whole path, and the OTI tangent agreed with a finite difference of
the original at several states along it. Compiling is not working,
and running is not verified.

## Where every entry stands

| status | entries |
| --- | --- |
| `acquired` | 126 |
| `metadata_resolved` | 11 |
| `transformed` | 41 |
| `compiled` | 9 |
| `abaqus_original_passed` | 8 |
| `abaqus_transformed_passed` | 62 |
| `primal_parity_passed` | 39 |
| `fully_verified` | 41 |
| `not_a_umat` | 50 |
| `blocked_with_evidence` | 4 |

## Reconciliation problems

- irfancn__Abaqus-UEL-elastic/uel_elastic.for is promoted into umat/ but its status is 'compiled', not fully_verified
- Jeff97__growth-of-circular-plate/Bending/Growth-CASE1.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-4/Experiment-ECOFLEX0030-Flat/Th01/BodyForce-Growth-2Stages.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/Flat/Th01/BodyForce-Growth-2Stages.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/HelixUp/Th01/BodyForce-Growth-2Stages.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/Flat/Th001/BodyForce-Growth-2Stages.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-4/Experiment-ECOFLEX0030-Flat/Th005/BodyForce-Growth-2Stages.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ParabolicDown/Th001/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-4/Experiment-ECOFLEX0030-ArcDown/Th005/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/HelixUp/Th01/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th001/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/HelixUp/Th001/PureGravity.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-4/Experiment-DRAGONSKIN20-ArcDown/Th01/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-4/Experiment-ECOFLEX0030-ArcDown/Th01/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th01/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/Flat/Th005/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th002/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ParabolicDown/Th005/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th01/PureGravity.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/Flat/Th002/PureGrowth.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/Flat/Th001/PureGrowth.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-4/Experiment-ECOFLEX0030-Flat/Th005/PureGrowth.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ParabolicUp/Th002/PureGrowth.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th01/PureGrowth.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th005/PureGrowth.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th005/PureGrowth.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-4/Experiment-DRAGONSKIN20-Flat/Th005/PureGrowth.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/Flat/Th01/PureGrowth.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-4/Experiment-DRAGONSKIN20-Flat/Th01/PureGrowth.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/Flat/Th005/PureGrowth.for is promoted into umat/ but its status is 'primal_parity_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ParabolicDown/Th002/PureGrowth.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ParabolicUp/Th001/PureGrowth.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ParabolicDown/Th01/PureGrowth.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Realization-of-planar-and-surface-conformal-mappings/Analytical_Example/3D/InputFile/Growth-MinSur3.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Realization-of-planar-and-surface-conformal-mappings/Analytical_Example/3D/MMAFile/Example4-Torus/Growth-MinSur3.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Realization-of-planar-and-surface-conformal-mappings/Analytical_Example/3D/MMAFile/Example3-Sphere/Growth-MinSur3.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Realization-of-planar-and-surface-conformal-mappings/Mesh_Convergence_test/3D/Sphere/10/Growth-Sphere.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- Jeff97__Realization-of-planar-and-surface-conformal-mappings/Instability_Analysis/Growth-Sphere.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- mholla__growth/umats/umat_area_morph.f is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- mholla__growth/umats/umat_fiber_morph.f is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- RitioL__PolyFatigueCrackSim/workplace/huang_umat_97.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- RitioL__PolyFatigueCrackSim/CPFEM-val/subroutines_revised.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- RitioL__PolyFatigueCrackSim/workplace/subroutines3_revised.for is promoted into umat/ but its status is 'abaqus_transformed_passed', not fully_verified
- AlexanderJFDR__Hyperelastic_phase_field/umat/NeoHookean_umat.for reached fully_verified but was not promoted into the verified collection
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th002/BodyForce-Growth-2Stages.for reached fully_verified but was not promoted into the verified collection
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th001/BodyForce-Growth-2Stages.for reached fully_verified but was not promoted into the verified collection
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th002/BodyForce-Growth-2Stages.for reached fully_verified but was not promoted into the verified collection
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th005-Visualization/BodyForce-Growth-2Stages.for reached fully_verified but was not promoted into the verified collection
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/Flat/Th002-Visualization/BodyForce-Growth-2Stages.for reached fully_verified but was not promoted into the verified collection
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/Flat/Th002/BodyForce-Growth-2Stages.for reached fully_verified but was not promoted into the verified collection
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ParabolicDown/Th002/BodyForce-Growth-2Stages.for reached fully_verified but was not promoted into the verified collection
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ParabolicDown/Th005/BodyForce-Growth-2Stages.for reached fully_verified but was not promoted into the verified collection
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-4/Experiment-DRAGONSKIN20-ArcDown/Th01/PureGrowth.for reached fully_verified but was not promoted into the verified collection
- Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/PathSensitivity/Th001-1MPa/BodyForce-Growth-GravityFirst.for reached fully_verified but was not promoted into the verified collection
- irfancn__Abaqus-UMAT-viscoelastic/umat_viscoelastic.for reached fully_verified but was not promoted into the verified collection
- keisuke58__pde-fem-biofilm/umat_biofilm_visco_phase2.f reached fully_verified but was not promoted into the verified collection
- mholla__BMMB24/simulations/input files/umat_transverseIsotropicStretch.f reached fully_verified but was not promoted into the verified collection
- mholla__growth/umats/umat_area_stretch.f reached fully_verified but was not promoted into the verified collection
- mholla__growth/umats/umat_iso_stretch.f reached fully_verified but was not promoted into the verified collection
- mholla__growth/umats/umat_transverse.f reached fully_verified but was not promoted into the verified collection

## Every UMAT entry

| source                                                     | status                     | iface |    primal |   tangent | states |
|------------------------------------------------------------|----------------------------|-------|-----------|-----------|--------|
| simcoon/testBin/Umats/UMABA/external/UMAT_ABAQUS_ELASTIC.f | transformed                | -     |         - |         - |      - |
| b_materials/UMATERIALS/CAUCHY3D-DP/hyplast_Cauchy3D-DP.for | transformed                | -     |         - |         - |      - |
| derJFDR__Hyperelastic_phase_field/umat/NeoHookean_umat.for | fully_verified             | -     |  0.00e+00 |  8.13e-10 |    2/2 |
| gyrosKarakalas__UMAT_3D/UMAT_3D_Coupled_ML_IP_Original.for | transformed                | -     |         - |         - |      - |
| enics-constitutive/examples/umat/src/umat_linear_elastic.f | transformed                | -     |         - |         - |      - |
| ahtiri__ABAQUS-Multiphysics-Diffusion-UEL/Diffusion_3D.for | acquired                   | UMAT  |         - |         - |      - |
| BristolCompositesInstitute__abaci/example/src/umat.f       | acquired                   | UMAT  |         - |         - |      - |
| BristolCompositesInstitute__abaci/test/data/umat.f         | fully_verified             | -     |  0.00e+00 |  1.12e-14 |    4/4 |
| istolCompositesInstitute__abaqus-modern-fortran/src/umat.f | acquired                   | UMAT  |         - |         - |      - |
| utine-for-3D-Composite-fatigue-simulation-Fortran-Code.for | acquired                   | UMAT  |         - |         - |      - |
| CAE_ASSISTANT_UMAT_Subroutine_ABAQUS_COMPOSITE_FATIGUE.for | transformed                | -     |         - |         - |      - |
| stant-Group__Abaqus-UEL-Subroutine/Abaqus_UEL_Subroutine.f | acquired                   | UMAT  |         - |         - |      - |
| mposite-curing/Path_Dependent-Abaqus-Curing-Subroutine.for | blocked_with_evidence      | -     |         - |         - |      - |
| c-Elasticity-Isothermal-Suboutine/ISOTROPIC-ELASTICITY.for | fully_verified             | -     |  0.00e+00 |  1.07e-14 |    4/4 |
| thotropic-Composite-Subroutine/PLANESTRESS-ORTHOTROPIC.for | primal_parity_passed       | -     |  0.00e+00 |  1.02e-13 |    2/2 |
| composite-curing/Abaqus-Viscoelastic-Curing-Subroutine.for | acquired                   | UMAT  |         - |         - |      - |
| stensen_FailureIndex/Subroutine/christensen_subroutine.for | transformed                | -     |         - |         - |      - |
| __critical-soil-models/src/models/bingham/umat_bingham.f90 | acquired                   | UMAT  |         - |         - |      - |
| CriticalSoilModels__critical-soil-models/src/umat.f90      | acquired                   | UMAT  |         - |         - |      - |
| CriticalSoilModels__incremental-driver/src/elastic.f90     | transformed                | -     |         - |         - |      - |
| ulator/ViscoelasticRVEs/umat3dorthotropic_viscoelastic.for | transformed                | -     |         - |         - |      - |
| aei__Implant-Fibrotic-Capsule/CellMatrixModel_20241204.for | acquired                   | UMAT  |         - |         - |      - |
| uaTT__STEEL-3dPointClouds/AutoGen/ALLcombinedSolid_CMN.for | acquired                   | UMAT  |         - |         - |      - |
| uaTT__STEEL-3dPointClouds/AutoGen/ALLcombinedSolid_DMN.for | acquired                   | UMAT  |         - |         - |      - |
| echanics__Paraqus/examples/example_abaqus_extrusion_umat.f | transformed                | -     |         - |         - |      - |
| _Trafos_Carbon_Repartitioning/simulations/UMAT/umat_main.f | acquired                   | UMAT  |         - |         - |      - |
| _Gradient_Enhanced_Damage_UMAT/src/UMAT_DamThermMech_1_H.f | acquired                   | UMAT  |         - |         - |      - |
| control-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Axe.for | abaqus_transformed_passed  | -     |  1.92e-04 |         - |      - |
| ontrol-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Disk.for | abaqus_transformed_passed  | -     |  7.45e-02 |         - |      - |
| rol-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Scallop.for | abaqus_transformed_passed  | -     |  3.46e-03 |         - |      - |
| f-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-DupinCyclide.for | abaqus_transformed_passed  | -     |  1.31e-01 |         - |      - |
| trol-of-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-Genhel.for | abaqus_transformed_passed  | -     |  1.80e+00 |         - |      - |
| trol-of-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-Saddle.for | abaqus_transformed_passed  | -     |  1.70e-01 |         - |      - |
| ntrol-of-shell/Abaqus_Files/3Dto3D/From-3D-to-3D-Petal.for | abaqus_transformed_passed  | -     |  1.15e+00 |         - |      - |
| ol-of-shell/Abaqus_Files/3Dto3D/From-3D-to-3D-SeaShell.for | abaqus_transformed_passed  | -     |  1.75e+00 |         - |      - |
| control-of-shell/Abaqus_Files/Alex_Shocked/Growth-Alex.for | abaqus_transformed_passed  | -     |  2.72e-07 |         - |      - |
| e-control-of-shell/Abaqus_Files/Beetle_Taxi/Growth-Car.for | abaqus_original_passed     | -     |         - |         - |      - |
| -control-of-shell/Abaqus_Files/FaceChange/Growth-Robot.for | abaqus_transformed_passed  | -     |  1.95e+00 |         - |      - |
| es-In-Section-3/ArcDown/Th001/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  2.31e-07 |    2/2 |
| Forces/Examples-In-Section-3/ArcDown/Th001/PureGravity.for | primal_parity_passed       | -     |  3.13e-08 |  4.19e-08 |    4/4 |
| -Forces/Examples-In-Section-3/ArcDown/Th001/PureGrowth.for | fully_verified             | -     |  2.06e-12 |  2.31e-07 |    2/2 |
| es-In-Section-3/ArcDown/Th002/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  5.65e-08 |    2/2 |
| Forces/Examples-In-Section-3/ArcDown/Th002/PureGravity.for | primal_parity_passed       | -     |  2.77e-09 |  5.08e-09 |    4/4 |
| -Forces/Examples-In-Section-3/ArcDown/Th002/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  5.65e-08 |    2/2 |
| 3/ArcDown/Th005-Visualization/BodyForce-Growth-2Stages.for | fully_verified             | -     |  2.33e-05 |  3.66e-09 |    2/2 |
| es-In-Section-3/ArcDown/Th005/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  1.71e-12 |  1.11e-06 |    1/2 |
| -Forces/Examples-In-Section-3/ArcDown/Th005/PureGrowth.for | primal_parity_passed       | -     |  1.71e-12 |  1.11e-06 |    1/2 |
| les-In-Section-3/ArcDown/Th01/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  1.77e-05 |    1/2 |
| -Forces/Examples-In-Section-3/ArcDown/Th01/PureGravity.for | primal_parity_passed       | -     |  5.45e-06 |  4.38e-09 |    4/4 |
| y-Forces/Examples-In-Section-3/ArcDown/Th01/PureGrowth.for | primal_parity_passed       | -     |  0.00e+00 |  1.77e-05 |    1/2 |
| ples-In-Section-3/ArcUp/Th001/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  1.03e-07 |    2/2 |
| dy-Forces/Examples-In-Section-3/ArcUp/Th001/PureGrowth.for | fully_verified             | -     |  7.75e-12 |  1.03e-07 |    2/2 |
| ples-In-Section-3/ArcUp/Th002/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  1.85e-07 |    2/2 |
| dy-Forces/Examples-In-Section-3/ArcUp/Th002/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  1.85e-07 |    2/2 |
| n-3/ArcUp/Th005-Visualization/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  3.66e-09 |    2/2 |
| ples-In-Section-3/ArcUp/Th005/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  1.88e-05 |    1/2 |
| dy-Forces/Examples-In-Section-3/ArcUp/Th005/PureGrowth.for | primal_parity_passed       | -     |  0.00e+00 |  1.88e-05 |    1/2 |
| mples-In-Section-3/ArcUp/Th01/BodyForce-Growth-2Stages.for | fully_verified             | -     |  3.69e-11 |  6.59e-07 |    2/2 |
| dy-Forces/Examples-In-Section-3/ArcUp/Th01/PureGravity.for | primal_parity_passed       | -     |  5.45e-06 |  4.38e-09 |    4/4 |
| ody-Forces/Examples-In-Section-3/ArcUp/Th01/PureGrowth.for | fully_verified             | -     |  3.69e-11 |  6.59e-07 |    2/2 |
| mples-In-Section-3/Flat/Th001/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  2.68e-11 |    2/2 |
| ody-Forces/Examples-In-Section-3/Flat/Th001/PureGrowth.for | primal_parity_passed       | -     |  0.00e+00 |  2.68e-11 |    4/4 |
| on-3/Flat/Th002-Visualization/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  3.64e-09 |    2/2 |
| mples-In-Section-3/Flat/Th002/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  2.68e-11 |    2/2 |
| ody-Forces/Examples-In-Section-3/Flat/Th002/PureGrowth.for | primal_parity_passed       | -     |  0.00e+00 |  2.68e-11 |    4/4 |
| on-3/Flat/Th005-Visualization/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  3.66e-09 |    2/2 |
| mples-In-Section-3/Flat/Th005/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  2.68e-11 |    2/2 |
| dy-Forces/Examples-In-Section-3/Flat/Th005/PureGravity.for | primal_parity_passed       | -     |  3.19e-05 |  4.58e-09 |    4/4 |
| ody-Forces/Examples-In-Section-3/Flat/Th005/PureGrowth.for | primal_parity_passed       | -     |  0.00e+00 |  2.68e-11 |    4/4 |
| amples-In-Section-3/Flat/Th01/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  5.47e-12 |  2.68e-11 |    4/4 |
| Body-Forces/Examples-In-Section-3/Flat/Th01/PureGrowth.for | primal_parity_passed       | -     |  0.00e+00 |  2.68e-11 |    4/4 |
| es-In-Section-3/HelixUp/Th001/BodyForce-Growth-2Stages.for | fully_verified             | -     |  2.10e-09 |  5.68e-11 |    2/2 |
| Forces/Examples-In-Section-3/HelixUp/Th001/PureGravity.for | abaqus_transformed_passed  | -     |  1.66e-10 |         - |      - |
| es-In-Section-3/HelixUp/Th002/BodyForce-Growth-2Stages.for | fully_verified             | -     |  6.76e-11 |  5.38e-11 |    2/2 |
| Forces/Examples-In-Section-3/HelixUp/Th002/PureGravity.for | fully_verified             | -     |  9.31e-11 |  7.73e-11 |    2/2 |
| -Forces/Examples-In-Section-3/HelixUp/Th002/PureGrowth.for | fully_verified             | -     |  6.76e-11 |  5.38e-11 |    2/2 |
| es-In-Section-3/HelixUp/Th005/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  5.14e-11 |    2/2 |
| Forces/Examples-In-Section-3/HelixUp/Th005/PureGravity.for | fully_verified             | -     |  0.00e+00 |  5.14e-11 |    2/2 |
| -Forces/Examples-In-Section-3/HelixUp/Th005/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  5.14e-11 |    2/2 |
| les-In-Section-3/HelixUp/Th01/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  5.96e-08 |    2/2 |
| -Forces/Examples-In-Section-3/HelixUp/Th01/PureGravity.for | primal_parity_passed       | -     |  0.00e+00 |  3.64e-07 |    2/2 |
| Section-3/ParabolicDown/Th001/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  3.92e-11 |    2/2 |
| /Examples-In-Section-3/ParabolicDown/Th001/PureGravity.for | primal_parity_passed       | -     |  3.13e-08 |  4.19e-08 |    4/4 |
| Section-3/ParabolicDown/Th002/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  4.05e-11 |    2/2 |
| s/Examples-In-Section-3/ParabolicDown/Th002/PureGrowth.for | abaqus_transformed_passed  | -     |  4.89e-10 |         - |      - |
| Section-3/ParabolicDown/Th005/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  8.26e-11 |    2/2 |
| /Examples-In-Section-3/ParabolicDown/Th005/PureGravity.for | primal_parity_passed       | -     |  3.19e-05 |  4.58e-09 |    4/4 |
| es/Examples-In-Section-3/ParabolicDown/Th01/PureGrowth.for | abaqus_transformed_passed  | -     |  4.18e-10 |         - |      - |
| ces/Examples-In-Section-3/ParabolicUp/Th001/PureGrowth.for | abaqus_transformed_passed  | -     |  2.28e-09 |         - |      - |
| ces/Examples-In-Section-3/ParabolicUp/Th002/PureGrowth.for | abaqus_transformed_passed  | -     |  1.13e-09 |         - |      - |
| In-Section-3/ParabolicUp/Th01/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  5.68e-08 |    2/2 |
| ion-4/Experiment-DRAGONSKIN20-ArcDown/Th01/PureGravity.for | primal_parity_passed       | -     |  1.42e-08 |  1.83e-08 |    4/4 |
| tion-4/Experiment-DRAGONSKIN20-ArcDown/Th01/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  7.50e-07 |    2/2 |
| ection-4/Experiment-DRAGONSKIN20-Flat/Th005/PureGrowth.for | primal_parity_passed       | -     |  0.00e+00 |  3.00e-07 |    2/2 |
| Section-4/Experiment-DRAGONSKIN20-Flat/Th01/PureGrowth.for | abaqus_transformed_passed  | -     |  2.21e-10 |         - |      - |
| ion-4/Experiment-ECOFLEX0030-ArcDown/Th005/PureGravity.for | primal_parity_passed       | -     |  2.75e-06 |  2.15e-09 |    4/4 |
| tion-4/Experiment-ECOFLEX0030-ArcDown/Th01/PureGravity.for | primal_parity_passed       | -     |  1.26e-08 |  1.94e-08 |    4/4 |
| riment-ECOFLEX0030-Flat/Th005/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  1.19e-07 |    2/2 |
| Section-4/Experiment-ECOFLEX0030-Flat/Th005/PureGrowth.for | primal_parity_passed       | -     |  0.00e+00 |  1.19e-07 |    2/2 |
| eriment-ECOFLEX0030-Flat/Th01/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  1.24e-11 |  3.32e-11 |    2/2 |
| thSensitivity/Th001-1MPa/BodyForce-Growth-GravityFirst.for | fully_verified             | -     |  0.00e+00 |  5.64e-11 |    2/2 |
| thSensitivity/Th001-5MPa/BodyForce-Growth-Simultaneous.for | primal_parity_passed       | -     |  0.00e+00 |  1.94e-06 |    1/2 |
| mal-mappings/Analytical_Example/2D/inputFile/Growth-EX.for | abaqus_transformed_passed  | -     |  1.82e-02 |         - |      - |
| mal-mappings/Analytical_Example/2D/inputFile/Growth-Z2.for | abaqus_transformed_passed  | -     |  5.90e-04 |         - |      - |
| l-mappings/Analytical_Example/2D/inputFile/Growth-frac.for | abaqus_transformed_passed  | -     |  4.28e-02 |         - |      - |
| appings/Analytical_Example/3D/InputFile/Growth-MinSur1.for | abaqus_transformed_passed  | -     |  8.99e-01 |         - |      - |
| appings/Analytical_Example/3D/InputFile/Growth-MinSur2.for | abaqus_transformed_passed  | -     |  6.89e-01 |         - |      - |
| appings/Analytical_Example/3D/InputFile/Growth-MinSur3.for | abaqus_transformed_passed  | -     |  4.60e-01 |         - |      - |
| /Analytical_Example/3D/MMAFile/Example1/Growth-MinSur1.for | abaqus_transformed_passed  | -     |  8.99e-01 |         - |      - |
| /Analytical_Example/3D/MMAFile/Example2/Growth-MinSur2.for | abaqus_transformed_passed  | -     |  7.17e-02 |         - |      - |
| ical_Example/3D/MMAFile/Example3-Sphere/Growth-MinSur3.for | abaqus_transformed_passed  | -     |  1.72e+00 |         - |      - |
| tical_Example/3D/MMAFile/Example4-Torus/Growth-MinSur3.for | abaqus_transformed_passed  | -     |  1.72e+00 |         - |      - |
| l-mappings/Bunny/Part1/ABAQUS_files/Growth-Bunny-Part1.for | compiled                   | -     |         - |         - |      - |
| l-mappings/Bunny/Part2/ABAQUS_files/Growth-Bunny-Part2.for | compiled                   | -     |         - |         - |      - |
| al-mappings/Hunman_face/ABAQUS_files/Growth-Human-face.for | abaqus_original_passed     | -     |         - |         - |      - |
| -conformal-mappings/Instability_Analysis/Growth-Sphere.for | abaqus_transformed_passed  | -     |  4.60e-01 |         - |      - |
| rmal-mappings/Mesh_Convergence_test/2D/EX/10/Growth-EX.for | abaqus_transformed_passed  | -     |  1.82e-02 |         - |      - |
| -mappings/Mesh_Convergence_test/2D/Frac/10/Growth-Frac.for | abaqus_transformed_passed  | -     |  1.34e+00 |         - |      - |
| rmal-mappings/Mesh_Convergence_test/2D/Z2/10/Growth-Z2.for | abaqus_transformed_passed  | -     |  1.26e-02 |         - |      - |
| s/Mesh_Convergence_test/3D/Catenoid/10/Growth-Catenoid.for | abaqus_transformed_passed  | -     |  1.83e+00 |         - |      - |
| s/Mesh_Convergence_test/3D/Helicoid/10/Growth-Helicoid.for | abaqus_transformed_passed  | -     |  1.36e-01 |         - |      - |
| pings/Mesh_Convergence_test/3D/Sphere/10/Growth-Sphere.for | abaqus_transformed_passed  | -     |  2.65e-01 |         - |      - |
| -mappings/Mesh_Convergence_test/Alex/20470/Growth-Alex.for | abaqus_original_passed     | -     |         - |         - |      - |
| al-mappings/Mesh_Convergence_test/Alex/749/Growth-Alex.for | abaqus_original_passed     | -     |         - |         - |      - |
| ormal-mappings/Model_car/ABAQUS_files/Growth-Model-car.for | compiled                   | -     |         - |         - |      - |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE1.for  | abaqus_transformed_passed  | -     |  2.00e+00 |         - |      - |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE2.for  | primal_parity_passed       | -     |  1.69e-05 |  1.65e-05 |    2/2 |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE3.for  | abaqus_transformed_passed  | -     |  2.77e-01 |         - |      - |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE1.for | abaqus_transformed_passed  | -     |  3.07e-01 |         - |      - |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE2.for | primal_parity_passed       | -     |  1.15e-04 |  7.28e-06 |    1/2 |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE3.for | primal_parity_passed       | -     |  9.55e-06 |  3.86e-05 |    0/2 |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE1.for | abaqus_transformed_passed  | -     |  4.21e-01 |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE2.for | abaqus_transformed_passed  | -     |  3.51e-04 |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE3.for | abaqus_transformed_passed  | -     |  1.81e-01 |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE4.for | abaqus_transformed_passed  | -     |  9.40e-01 |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE5.for | abaqus_original_passed     | -     |         - |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE6.for | primal_parity_passed       | -     |  4.83e-05 |  4.46e-06 |    0/2 |
| 7__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-101.for | abaqus_transformed_passed  | -     |  1.98e+00 |         - |      - |
| 7__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-102.for | abaqus_transformed_passed  | -     |  2.00e+00 |         - |      - |
| 7__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-103.for | abaqus_transformed_passed  | -     |  1.94e+00 |         - |      - |
| 97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-11.for | abaqus_transformed_passed  | -     |  1.64e+00 |         - |      - |
| 97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-12.for | abaqus_transformed_passed  | -     |  2.00e+00 |         - |      - |
| 97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-13.for | abaqus_transformed_passed  | -     |  1.84e+00 |         - |      - |
| owth-of-shell/Input files and UMAT/Example1/SweetMelon.for | abaqus_transformed_passed  | -     |  6.47e-03 |         - |      - |
| th-of-shell/Input files and UMAT/Example2/MorningGlory.for | primal_parity_passed       | -     |  3.20e-03 |  1.95e-05 |    4/4 |
| _growth-of-shell/Input files and UMAT/Example3/Trachea.for | abaqus_transformed_passed  | -     |  2.03e-03 |         - |      - |
| 7__growth-of-shell/Input files and UMAT/Example4/Apple.for | compiled                   | -     |         - |         - |      - |
| l/Input files and UMAT/Example5/CereusForbesiiSpiralis.for | abaqus_transformed_passed  | -     |  1.41e+00 |         - |      - |
| f-shell/Input files and UMAT/Example6/TendrilOfPumpkin.for | primal_parity_passed       | -     |  8.32e-03 |         - |    0/4 |
| uliaFEM__UMAT.jl/umat_models/drucker_prager_plasticity.f90 | acquired                   | UMAT  |         - |         - |      - |
| JuliaFEM__UMAT.jl/umat_models/gurson_porous_plasticity.f90 | acquired                   | UMAT  |         - |         - |      - |
| KianAbd__vCANN_FEM/Abaqus/umat.f90                         | acquired                   | UMAT  |         - |         - |      - |
| KianAbd__vCANN_FEM/Abaqus/umat_vCANN.f90                   | acquired                   | UMAT  |         - |         - |      - |
| KianAbd__vCANN_FEM/Abaqus/umat_vCANN.for                   | acquired                   | UMAT  |         - |         - |      - |
| ow/Results_Liao_Thermo/20260601-103627/UMAT/umat_vCANN.for | acquired                   | UMAT  |         - |         - |      - |
| terialModels/models/CrystalPlasticity/src/taylor_model.f90 | acquired                   | UMAT  |         - |         - |      - |
| lModels/models/GenFiniteStrain/src/GeneralFiniteStrain.for | acquired                   | UMAT  |         - |         - |      - |
| ialModels/models/GenSmallStrain/src/GeneralSmallStrain.f90 | acquired                   | UMAT  |         - |         - |      - |
| KnutAM__MaterialModels/models/MM2021/src/umat.f90          | acquired                   | UMAT  |         - |         - |      - |
| KnutAM__MaterialModels/models/Qin2018/src/umat.f90         | acquired                   | UMAT  |         - |         - |      - |
| lyLabTCD__localBasisAbaqus/Case studies/umat_MA_global.for | acquired                   | UMAT  |         - |         - |      - |
| llyLabTCD__localBasisAbaqus/Case studies/umat_MA_local.for | acquired                   | UMAT  |         - |         - |      - |
| bre reinforced anistropic models/Abaqus/umat_MA_global.for | acquired                   | UMAT  |         - |         - |      - |
| ibre reinforced anistropic models/Abaqus/umat_MA_local.for | acquired                   | UMAT  |         - |         - |      - |
| -QMUL__PhaseFieldComp/Subroutine/UELUMATPhaseField_AT2.for | metadata_resolved          | -     |         - |         - |      - |
| PeriDoX__PeriDoX/Publications/2022_JOSS/data/UMAT/base.f   | transformed                | -     |         - |         - |      - |
| PeriHub__PeriLab.jl/src/Models/Material/UMATs/base.f       | transformed                | -     |         - |         - |      - |
| PeriHub__PeriLab.jl/src/Models/Material/UMATs/usertest.f   | acquired                   | UMAT  |         - |         - |      - |
| ls/fortran_models/linear_elastic/UMAT_LinearElasticity.f90 | transformed                | -     |         - |         - |      - |
| utiveModels/fortran_models/mohr_coulomb/UMAT_MohrCoulomb.f | transformed                | -     |         - |         - |      - |
| alMichalczyk__PavementDesign/Subroutines/umat_gmaxwell.for | transformed                | -     |         - |         - |      - |
| alMichalczyk__PavementDesign/Subroutines/umat_ms_plast.for | transformed                | -     |         - |         - |      - |
| ReachOptimum__mlpcp-interp-dic/abaqus/UMMDp_FLC.f          | acquired                   | UMAT  |         - |         - |      - |
| RickAlb__UMAT-DFD-Lebedev/all_subroutines/UMAT_DFD_LEB.for | acquired                   | UMAT  |         - |         - |      - |
| ioL__PolyFatigueCrackSim/CPFEM-val/subroutines_revised.for | abaqus_transformed_passed  | -     |  1.87e+00 |         - |      - |
| RitioL__PolyFatigueCrackSim/workplace/huang_umat_97.for    | abaqus_transformed_passed  | -     |  1.88e+00 |         - |      - |
| oL__PolyFatigueCrackSim/workplace/subroutines3_revised.for | abaqus_transformed_passed  | -     |  1.87e+00 |         - |      - |
| /OXFORD-UMAT/Example - Polycrytal with PROPS/OXFORD-UMAT.f | acquired                   | UMAT  |         - |         - |      - |
| S/OXFORD-UMAT/Example - Residual deformation/OXFORD-UMAT.f | acquired                   | UMAT  |         - |         - |      - |
| on__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v2.26/OXFORD-UMAT.f | acquired                   | UMAT  |         - |         - |      - |
| oon__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v3.1/OXFORD-UMAT.f | acquired                   | UMAT  |         - |         - |      - |
| oon__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v3.3/OXFORD-UMAT.f | acquired                   | UMAT  |         - |         - |      - |
| na-Taghizadeh__UMAT_Hyperelastic/CompresibleNeoHookean.for | fully_verified             | -     |  0.00e+00 |  8.07e-10 |    2/2 |
| oowinehouse__ABQ-UMAT-Sanisand-High/src/interface/umat.f90 | acquired                   | UMAT  |         - |         - |      - |
| Woowinehouse__Abaqus_UMAT_sanisand/merge/source.F90        | compiled                   | -     |         - |         - |      - |
| Woowinehouse__Abaqus_UMAT_sanisand/src/interface/umat.f90  | acquired                   | UMAT  |         - |         - |      - |
| 20314-abqus-simulation/abaqus/enhanced/enhanced_curing.for | abaqus_original_passed     | -     |         - |         - |      - |
| bqus-simulation/abaqus/original/array_with_two_pixel_z.for | abaqus_transformed_passed  | -     |       inf |         - |      - |
| 4-abqus-simulation/abaqus/simplified/simplified_curing.for | abaqus_transformed_passed  | -     |       inf |         - |      - |
| flow/examples/07_SubroutineJob/subroutine/umat_elastic.for | metadata_resolved          | -     |         - |         - |      - |
| abuganza__BayesianCalibrationSkinGrowth/GOH_Example.f      | acquired                   | UMAT  |         - |         - |      - |
| abuganza__BayesianCalibrationSkinGrowth/Iso_Example.f      | metadata_resolved          | -     |         - |         - |      - |
| nGrowth/Revision/Abaqus SImulation/GOH/BC1_50cc/GOH_50cc.f | acquired                   | UMAT  |         - |         - |      - |
| nGrowth/Revision/Abaqus SImulation/GOH/BC1_55cc/GOH_55cc.f | acquired                   | UMAT  |         - |         - |      - |
| h/Revision/Abaqus SImulation/Isotropic/BC1_50cc/Iso_50cc.f | metadata_resolved          | -     |         - |         - |      - |
| h/Revision/Abaqus SImulation/Isotropic/BC1_60cc/Iso_60cc.f | metadata_resolved          | -     |         - |         - |      - |
| h/Revision/Abaqus SImulation/Isotropic/BC2_60cc/Iso_60cc.f | metadata_resolved          | -     |         - |         - |      - |
| /Revision/Abaqus SImulation/SampleSimulation/GOH_Example.f | acquired                   | UMAT  |         - |         - |      - |
| /Revision/Abaqus SImulation/SampleSimulation/Iso_Example.f | metadata_resolved          | -     |         - |         - |      - |
| nza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_strain.f | abaqus_transformed_passed  | -     |  1.43e-06 |         - |      - |
| nza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_stress.f | primal_parity_passed       | -     |  0.00e+00 |         - |      - |
| abuganza__UMAT_anisotropic_damage/UMAT_Tissue_3d.f         | abaqus_transformed_passed  | -     |  7.01e-06 |         - |      - |
| adtzlr__ttb/docs/examples/Abaqus/umat_nh_ttb.f             | acquired                   | UMAT  |         - |         - |      - |
| adtzlr__ttb/docs/examples/Abaqus/umat_nh_ttb_simple.f      | acquired                   | UMAT  |         - |         - |      - |
| ahartloper__UVC_MatMod/Abaqus/UVCmultiaxial.for            | acquired                   | UMAT  |         - |         - |      - |
| ahartloper__UVC_MatMod/Abaqus/UVCplanestress.for           | transformed                | -     |         - |         - |      - |
| ahartloper__UVC_MatMod/Abaqus/UVCuniaxial.for              | acquired                   | UMAT  |         - |         - |      - |
| ahartloper__UVC_MatMod/Abaqus/UVCuniaxial_IS.for           | acquired                   | UMAT  |         - |         - |      - |
| artorg-unibe-ch__HFE/02_CODE/abq/UMAT_BIPHASIC.f           | transformed                | -     |         - |         - |      - |
| ic/HETVAL_nonLocalLemaitre/HETVAL_lemaitreDamageNonLocal.f | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| mage-UMAT-Public/nonLocalLemaitre/lemaitreDamageNonLocal.f | fully_verified             | -     |  0.00e+00 |  8.72e-16 |    2/2 |
| am/abaqusUMATs/abaqusUmatMohrCoulomb/MohrCoulombAbaqus.for | acquired                   | UMAT  |         - |         - |      - |
| bennifuchs__TsaiWu-Fortran/abaqus-umat-interface.f90       | acquired                   | UMAT  |         - |         - |      - |
| bennifuchs__TsaiWu-Fortran/umat.f90                        | acquired                   | UMAT  |         - |         - |      - |
| baqus/scriptbase/benchmark_abaqus_scripts/veni_mix_model.f | acquired                   | UMAT  |         - |         - |      - |
| us/scriptbase/benchmark_abaqus_scripts/vevp_leonov_model.f | transformed                | -     |         - |         - |      - |
| aqus/scriptbase/benchmark_abaqus_scripts/vp_leonov_model.f | transformed                | -     |         - |         - |      - |
| bmmbUPF__abaqusIVD/Sub_MechDisc.f                          | acquired                   | UMAT  |         - |         - |      - |
| bmmbUPF__abaqusIVD/Sub_TransDisc.f                         | acquired                   | UMAT  |         - |         - |      - |
| calculix__ccx_fff/src/umat.f                               | transformed                | -     |         - |         - |      - |
| compas-dev__compas_fea2/data/umat/umat-hooke-iso.f         | acquired                   | UMAT  |         - |         - |      - |
| pas-dev__compas_fea2/data/umat/umat-hooke-transversaliso.f | transformed                | -     |         - |         - |      - |
| cunhuav__Abaqus-Neural-Network-UMAT/ro_nn_umat.f90         | acquired                   | UMAT  |         - |         - |      - |
| damin225__short-crack-propagation-3d/input_clean/umat.f    | acquired                   | UMAT  |         - |         - |      - |
| davidmorinNTNU__ABAQUS_subroutines/V_UMAT/UMAT.f           | acquired                   | UMAT  |         - |         - |      - |
| ekurth__NEML/util/abaqus/nemlumat.f                        | acquired                   | UMAT  |         - |         - |      - |
| frodal__SCMM-hypo/HypoImp.f                                | acquired                   | UMAT  |         - |         - |      - |
| D_anisotropic_viscoelastic_model/OrthoWoodCreep_Column.for | transformed                | -     |         - |         - |      - |
| _anisotropic_viscoelastic_model/OrthoWoodCreep_General.for | transformed                | -     |         - |         - |      - |
| 3D_anisotropic_viscoelastic_model/Ortho_WoodCreep_Cube.for | transformed                | -     |         - |         - |      - |
| 6__3D_anisotropic_viscoelastic_model/TIRockCreep_CANEY.for | transformed                | -     |         - |         - |      - |
| _3D_anisotropic_viscoelastic_model/TIRockCreep_GENERAL.for | transformed                | -     |         - |         - |      - |
| hamza-djeloud__thesis_project/plate_with_notch.for         | primal_parity_passed       | -     |  0.00e+00 |  6.72e-15 |    4/4 |
| harshaa765__Bilinear-CZM-UMAT/Bilinear_CZM_UMAT.for        | metadata_resolved          | -     |         - |         - |      - |
| harshaa765__UMATFile/UMAT.for                              | compiled                   | -     |         - |         - |      - |
| hwu12sluedu__MaterialAI-Workbench/examples/UMAT/ml_umat.f  | acquired                   | UMAT  |         - |         - |      - |
| I-Workbench/material_ai_workbench/resources/umat/ml_umat.f | acquired                   | UMAT  |         - |         - |      - |
| ibf-RWTH__GA-Calibration/subroutine/Umat_CP.for            | acquired                   | UMAT  |         - |         - |      - |
| irfancn__Abaqus-UEL-elastic/uel_elastic.for                | compiled                   | -     |         - |         - |      - |
| irfancn__Abaqus-UMAT-elastic/umat_elastic.for              | fully_verified             | -     |  0.00e+00 |  1.00e-14 |    4/4 |
| irfancn__Abaqus-UMAT-viscoelastic/umat_viscoelastic.for    | fully_verified             | -     |  6.50e-05 |  1.00e-14 |    4/4 |
| __numgeo-hardening-soil-bricks/src/hs-bricks-umat/umat.f90 | acquired                   | UMAT  |         - |         - |      - |
| ing-soil-bricks/src/incremental-driver/material_models.f90 | acquired                   | UMAT  |         - |         - |      - |
| -machacek__numgeo-hypo-igs-isa-gis/src/material_models.f90 | acquired                   | UMAT  |         - |         - |      - |
| jacojvr__UMATs/UMAT_framework/umat_comb.f                  | acquired                   | UMAT  |         - |         - |      - |
| jacojvr__UMATs/UMAT_framework/umat_iso.f                   | acquired                   | UMAT  |         - |         - |      - |
| tine_skills/official_examples/umat/umat_elastic_official.f | compiled                   | -     |         - |         - |      - |
| ls/official_examples/umat/umat_mises_plasticity_official.f | compiled                   | -     |         - |         - |      - |
| urry__pipelining/elmerfem/fem/src/modules/ElasticSolve.F90 | acquired                   | UMAT  |         - |         - |      - |
| jpsferreira__UMAT-ABAQUS/src/_umat.for                     | acquired                   | UMAT  |         - |         - |      - |
| jpsferreira__UMAT-ABAQUS/test_in_abaqus/umat_general.for   | metadata_resolved          | -     |         - |         - |      - |
| jpsferreira__UMAT-ABAQUS/umat_general.for                  | metadata_resolved          | -     |         - |         - |      - |
| keisuke58__pde-fem-biofilm/umat_biofilm_visco.f            | acquired                   | UMAT  |         - |         - |      - |
| keisuke58__pde-fem-biofilm/umat_biofilm_visco_2ch.f        | transformed                | -     |         - |         - |      - |
| keisuke58__pde-fem-biofilm/umat_biofilm_visco_phase2.f     | fully_verified             | -     |  0.00e+00 |  4.15e-11 |    2/2 |
| llnl__ExaConstit/src/umats/umat.f                          | acquired                   | UMAT  |         - |         - |      - |
| MAT-constative-model/Duncan-Chang_EB_UMAT_ABAQUS6.14-5.for | acquired                   | UMAT  |         - |         - |      - |
| enchmark-cases/Benchmarks/Fuel_pellet_quarter/czmHealing.f | metadata_resolved          | -     |         - |         - |      - |
| enchmark-cases/Benchmarks/Notched_plate_shear/czmHealing.f | transformed                | -     |         - |         - |      - |
| luisez1988__Viscoplastic-NorSand/UMAT_Nor_Sand_Zamb.for    | acquired                   | UMAT  |         - |         - |      - |
| marioruiarruda__Hashin_2D_UMAT/umat_hashin_f90.f90         | acquired                   | UMAT  |         - |         - |      - |
| marioruiarruda__Hashin_3D_UMAT/umat_hashin3D_f90.f90       | transformed                | -     |         - |         - |      - |
| marioruiarruda__Mazars_UMAT/umat_mazars_f90.f90            | acquired                   | UMAT  |         - |         - |      - |
| marioruiarruda__Tsai-Wu_2D_UMAT/umat_tsaiwu_f90.f90        | acquired                   | UMAT  |         - |         - |      - |
| matmodlab__matmodlab2/matmodlab2/umat/uhyper_wrap.f90      | acquired                   | UMAT  |         - |         - |      - |
| modlab__matmodlab2/matmodlab2/umat/umats/umat_neohooke.f90 | acquired                   | UMAT  |         - |         - |      - |
| matmodlab__matmodlab2/matmodlab2/umat/umats/umat_stub.f90  | acquired                   | UMAT  |         - |         - |      - |
| b__matmodlab2/matmodlab2/umat/umats/umat_thermoelastic.f90 | transformed                | -     |         - |         - |      - |
| mauroarcidiacono__Crystal-Plasticity-UMAT/umat_abaqus.for  | acquired                   | UMAT  |         - |         - |      - |
| roarcidiacono__Crystal-Plasticity-UMAT/umat_standalone.for | acquired                   | UMAT  |         - |         - |      - |
| /simulations/input files/umat_transverseIsotropicStretch.f | fully_verified             | -     |  0.00e+00 |  7.30e-08 |    2/2 |
| mholla__SOFT24/simulations/UMAT_axon_tension.f             | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_area_morph.f                     | abaqus_transformed_passed  | -     |  7.96e-02 |         - |      - |
| mholla__growth/umats/umat_area_morph_Abaqus.f              | transformed                | -     |         - |         - |      - |
| mholla__growth/umats/umat_area_morph_orient.f              | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_area_stretch.f                   | fully_verified             | -     |  0.00e+00 |  1.35e-10 |    2/2 |
| mholla__growth/umats/umat_fiber_morph.f                    | abaqus_transformed_passed  | -     |  2.00e+00 |         - |      - |
| mholla__growth/umats/umat_fiber_morph_Abaqus.f             | transformed                | -     |         - |         - |      - |
| mholla__growth/umats/umat_fiber_morph_orient.f             | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_fiber_stretch.f                  | primal_parity_passed       | -     |  0.00e+00 |  9.87e-11 |    3/3 |
| mholla__growth/umats/umat_iso_Mandel.f                     | transformed                | -     |         - |         - |      - |
| mholla__growth/umats/umat_iso_Mandel_v2.f                  | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_iso_morph.f                      | abaqus_transformed_passed  | -     |  7.14e-02 |         - |      - |
| mholla__growth/umats/umat_iso_morph_Abaqus.f               | transformed                | -     |         - |         - |      - |
| mholla__growth/umats/umat_iso_stretch.f                    | fully_verified             | -     |  0.00e+00 |  1.35e-10 |    2/2 |
| mholla__growth/umats/umat_neohooke.f                       | transformed                | -     |         - |         - |      - |
| mholla__growth/umats/umat_neohooke_abaqus.f                | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_ortho_stretch.f                  | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_transverse.f                     | fully_verified             | -     |  0.00e+00 |  1.35e-10 |    2/2 |
| _Viscoelasticity/ABAQUS_DSR_EXAMPLE/ViscoelasticityCode3.f | acquired                   | UMAT  |         - |         - |      - |
| mrkearden__abaqus_umat/ElasticSolve.F90                    | acquired                   | UMAT  |         - |         - |      - |
| mrkearden__abaqus_umat/UMAT.F90                            | acquired                   | UMAT  |         - |         - |      - |
| rd_Crystal_Plasticity/ExampleInputFiles/HCPnoTwin/umat.for | acquired                   | UMAT  |         - |         - |      - |
| undar__PFM_UMAT_ElastoPlastic/UMAT_phasefield_plasticity.f | acquired                   | UMAT  |         - |         - |      - |
| us-explicit/examples/_pile_driving/HPP_Staubach_explicit.f | acquired                   | UMAT  |         - |         - |      - |
| trickstaubach__abaqus-explicit/src/HPP_Staubach_explicit.f | acquired                   | UMAT  |         - |         - |      - |
| peer-open-source__xara/SRC/domain/peri/umat.for            | acquired                   | UMAT  |         - |         - |      - |
| phhannequart__UMAT_sma_hannequart/UMAT_sma_hannequart.for  | acquired                   | UMAT  |         - |         - |      - |
| qusUMATs/abaqusUmatLinearElastic/abaqusUmatLinearElastic.f | acquired                   | UMAT  |         - |         - |      - |
| fortran-integration_using_Julia/src/Material_Models/umat.f | acquired                   | UMAT  |         - |         - |      - |
| -based Return Mapping - Fully-Implicit/umat_subroutine.for | acquired                   | UMAT  |         - |         - |      - |
| n-based Return Mapping - Semi-Implicit/umat_subroutine.for | acquired                   | UMAT  |         - |         - |      - |
| -based Return Mapping - Fully-Implicit/umat_subroutine.for | acquired                   | UMAT  |         - |         - |      - |
| s-based Return Mapping - Semi-Implicit/umat_subroutine.for | acquired                   | UMAT  |         - |         - |      - |
| elopment/src/elements/solid/materials/ABAQUS_BCJ/bcj_iso.f | acquired                   | UMAT  |         - |         - |      - |
| sas229__geomat/src/umat/src/umat.f90                       | acquired                   | UMAT  |         - |         - |      - |
| sd104400__OPA_Modeling/FE Modeling/UMAT_DPIsodwAniDM.for   | acquired                   | UMAT  |         - |         - |      - |
| seekzzh__mat-model-lab/assets/templates/abaqus_umat.f      | transformed                | -     |         - |         - |      - |
| shayansss__bioumat/SUBROUTINES.FOR                         | transformed                | -     |         - |         - |      - |
| shayansss__hml/NONLIPLS.for                                | transformed                | -     |         - |         - |      - |
| simoneponcioni__HFE/02_CODE/abq/UMAT_BIPHASIC.f            | transformed                | -     |         - |         - |      - |
| swayli94__AbaqusTools/LaRC05/umat.f90                      | acquired                   | UMAT  |         - |         - |      - |
| g48__CoupFE/examples/neo_hookean_umat/neo_hookean_umat.for | acquired                   | UMAT  |         - |         - |      - |
| tengzhang48__CoupFE/examples/ogden_umat/ogden_umat.for     | acquired                   | UMAT  |         - |         - |      - |
| __CoupFE/examples/small_strain_j2_umat/small_strain_j2.for | acquired                   | UMAT  |         - |         - |      - |
| all_strain_viscoelastic_umat/small_strain_viscoelastic.for | acquired                   | UMAT  |         - |         - |      - |
| ngzhang48__abaqus_ufl/examples/_template/template_umat.for | acquired                   | UMAT  |         - |         - |      - |
| _abaqus_ufl/examples/neo_hookean_umat/neo_hookean_umat.for | acquired                   | UMAT  |         - |         - |      - |
| tengzhang48__abaqus_ufl/examples/ogden_umat/ogden_umat.for | acquired                   | UMAT  |         - |         - |      - |
| aqus_ufl/examples/small_strain_j2_umat/small_strain_j2.for | acquired                   | UMAT  |         - |         - |      - |
| all_strain_viscoelastic_umat/small_strain_viscoelastic.for | acquired                   | UMAT  |         - |         - |      - |
| jason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_1EL.for | transformed                | -     |         - |         - |      - |
| jason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_2EL.for | abaqus_original_passed     | -     |         - |         - |      - |
| jason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_3EL.for | abaqus_original_passed     | -     |         - |         - |      - |
| _finite_viscoelasticity/report/chapters/VISC_OGDEN_2EL.for | blocked_with_evidence      | -     |         - |         - |      - |
| _viscoelasticity/simulation_input_files/VISC_OGDEN_1EL.for | transformed                | -     |         - |         - |      - |
| _viscoelasticity/simulation_input_files/VISC_OGDEN_2EL.for | blocked_with_evidence      | -     |         - |         - |      - |
| _viscoelasticity/simulation_input_files/VISC_OGDEN_3EL.for | blocked_with_evidence      | -     |         - |         - |      - |
| thelfer__tfel/mtest/tests/mtest/castem/umat.f              | acquired                   | UMAT  |         - |         - |      - |
| theysy__mml_subroutine_public/MML_U2/MML_U2.for            | abaqus_transformed_passed  | -     |  1.61e+00 |         - |      - |
| theysy__mml_subroutine_public/MML_U3/MML_U3.FOR            | abaqus_transformed_passed  | -     |  1.68e+00 |         - |      - |
| tmfrln__paraqus/examples/example_abaqus_extrusion_umat.f   | acquired                   | UMAT  |         - |         - |      - |
| rge/archives/fortran_fixed_form/yu_kinematic_3d_abaqus.for | acquired                   | UMAT  |         - |         - |      - |
| orge/archives/fortran_fixed_form/yu_kinematic_3d_fixed.for | acquired                   | UMAT  |         - |         - |      - |
| toruinaba__manforge/fortran/j2_isotropic_3d.f90            | acquired                   | UMAT  |         - |         - |      - |
| toruinaba__manforge/fortran/yu_kinematic_3d.f90            | acquired                   | UMAT  |         - |         - |      - |
| toruinaba__manforge/fortran/yu_kinematic_ps.f90            | acquired                   | UMAT  |         - |         - |      - |
| -Pamies/Examples/C3D8H/UT kappa_mu=1/UMAT_KLP_RK5_hybrid.f | acquired                   | UMAT  |         - |         - |      - |
| alsubbiah__Abaqus-Multi-scale-modelling/Abaqus/umatcode3.f | acquired                   | UMAT  |         - |         - |      - |
| ters_Reference/Adapters/Material/Adapters/UMAT_Adapter.f90 | acquired                   | UMAT  |         - |         - |      - |
| gacy_Adapters_Reference/Adapters/Material/UMAT_Adapter.f90 | acquired                   | UMAT  |         - |         - |      - |
