# Corpus verification

391 acquired artefacts, of which 349 present a UMAT interface to Abaqus.

**67 fully verified.**

`fully_verified` means the source transformed and compiled, Abaqus ran
the ORIGINAL, Abaqus ran the CONVERTED build on the same deck, their
stress and state histories agreed over the whole path, and the OTI
tangent agreed with a finite difference of the original at several
states along it. Compiling is not working and running is not verified.

## Finished, and unfinished

| | entries |
| --- | ---: |
| verified | 67 |
| blocked outside this repository | 116 |
| work remaining here | 208 |

## Every terminal state

| terminal state | whose move | entries |
| --- | --- | ---: |
| `transform_refused` | internal | 98 |
| `fully_verified` | verified | 67 |
| `not_a_umat` | external | 42 |
| `primal_disagreed` | internal | 42 |
| `missing_material_data` | external | 40 |
| `experiment_not_generated` | internal | 26 |
| `incomplete_or_corrupt_source` | external | 18 |
| `external_dependency_unavailable` | external | 16 |
| `transformed_job_failed` | internal | 13 |
| `original_job_failed` | internal | 10 |
| `unsupported_formulation` | internal | 6 |
| `tangent_not_verified` | internal | 6 |
| `derivative_truncated` | internal | 6 |
| `support_build_failed` | internal | 1 |

## What is left here, by cluster

Each of these is a limitation of this pipeline, not of the corpus. They are listed largest first because that is the order they are worth fixing in.

| cluster | entries |
| --- | ---: |
| `transform_refused` | 98 |
| `primal_disagreed` | 42 |
| `experiment_not_generated` | 26 |
| `transformed_job_failed` | 13 |
| `original_job_failed` | 10 |
| `unsupported_formulation` | 6 |
| `tangent_not_verified` | 6 |
| `derivative_truncated` | 6 |
| `support_build_failed` | 1 |

## What the transformer refused, and what those files are

141 sources were refused by the transformer. A REFUSAL IS A FACT ABOUT THE TRANSFORMER. Each of these was then classified by parsing the file itself -- its Abaqus entry point, its digest against every other acquired source, and an offline compile of the author's own text -- and the classification below rests on that evidence and never on the refusal.

| what the file is | entries |
| --- | ---: |
| `genuine_umat` | 96 |
| `missing_external_dependency` | 16 |
| `helper_or_module_only` | 12 |
| `incomplete_or_corrupt_source` | 12 |
| `duplicate_of_another_source` | 3 |
| `other_abaqus_routine` | 2 |

6 of them are held at `genuine_umat` because the offline compile did not settle whether the published text builds. That is the safe direction: it counts the work as ours.

## Every entry

| source | terminal state | element | primal | tangent | states |
| --- | --- | --- | ---: | ---: | --- |
| 3MAH__simcoon/testBin/Umats/UMABA/external/UMAT_ABAQUS_ELASTIC.f | `missing_material_data` |  |  |  |  |
| erical_geolab_materials/UMATERIALS/CAUCHY3D-DP/hyplast_Cauchy3D-DP.for | `missing_material_data` |  |  |  |  |
| AlexanderJFDR__Hyperelastic_phase_field/umat/NeoHookean_umat.for | `fully_verified` | C3D8 | 0.00e+00 | 8.43e-10 | 2/2 |
| AnargyrosKarakalas__UMAT_3D/UMAT_3D_Coupled_ML_IP_Original.for | `transform_refused` |  |  |  |  |
| Mresearch__fenics-constitutive/examples/umat/src/umat_linear_elastic.f | `missing_material_data` |  |  |  |  |
| BBahtiri__ABAQUS-Multiphysics-Diffusion-UEL/Diffusion_3D.for | `external_dependency_unavailable` |  |  |  |  |
| araFEM-lite/src/programs/dev/xx15/francesc/umat_DP_primal_CPPM_def.f90 | `not_a_umat` |  |  |  |  |
| Batmanabcdefg__ParaFEM-lite/src/programs/dev/xx15/plasticity_xx15.F90 | `not_a_umat` |  |  |  |  |
| BristolCompositesInstitute__abaci/example/src/umat.f | `transform_refused` |  |  |  |  |
| BristolCompositesInstitute__abaci/test/data/umat.f | `fully_verified` | C3D8 | 0.00e+00 | 1.12e-14 | 4/4 |
| BristolCompositesInstitute__abaqus-modern-fortran/src/umat.f | `transform_refused` |  |  |  |  |
| E-UMAT-subroutine-for-3D-Composite-fatigue-simulation-Fortran-Code.for | `incomplete_or_corrupt_source` |  |  |  |  |
| -simulation/CAE_ASSISTANT_UMAT_Subroutine_ABAQUS_COMPOSITE_FATIGUE.for | `missing_material_data` |  |  |  |  |
| CAEAssistant-Group__Abaqus-UEL-Subroutine/Abaqus_UEL_Subroutine.f | `incomplete_or_corrupt_source` |  |  |  |  |
| alysis-of-composite-curing/Path_Dependent-Abaqus-Curing-Subroutine.for | `missing_material_data` |  |  |  |  |
| qus-Isotropic-Elasticity-Isothermal-Suboutine/ISOTROPIC-ELASTICITY.for | `fully_verified` | C3D8 | 0.00e+00 | 1.07e-14 | 4/4 |
| Tsai-Hill-Orthotropic-Composite-Subroutine/PLANESTRESS-ORTHOTROPIC.for | `unsupported_formulation` | CPS4 |  |  |  |
| analysis-of-composite-curing/Abaqus-Viscoelastic-Curing-Subroutine.for | `incomplete_or_corrupt_source` |  |  |  |  |
| ostock__Christensen_FailureIndex/Subroutine/christensen_subroutine.for | `missing_material_data` |  |  |  |  |
| alSoilModels__critical-soil-models/src/models/bingham/umat_bingham.f90 | `external_dependency_unavailable` |  |  |  |  |
| CriticalSoilModels__critical-soil-models/src/umat.f90 | `external_dependency_unavailable` |  |  |  |  |
| CriticalSoilModels__incremental-driver/src/elastic.f90 | `missing_material_data` |  |  |  |  |
| tic-RVE-Calculator/ViscoelasticRVEs/umat3dorthotropic_viscoelastic.for | `missing_material_data` |  |  |  |  |
| ElmerCSC__elmerfem/fem/src/modules/ElasticSolve.F90 | `not_a_umat` |  |  |  |  |
| Farid-Alisafaei__Implant-Fibrotic-Capsule/CellMatrixModel_20241204.for | `transform_refused` |  |  |  |  |
| GuGuaTT__STEEL-3dPointClouds/AutoGen/ALLcombinedSolid_CMN.for | `transform_refused` |  |  |  |  |
| GuGuaTT__STEEL-3dPointClouds/AutoGen/ALLcombinedSolid_DMN.for | `transform_refused` |  |  |  |  |
| HIT-FSW-314__abaqus/abaqus-umat/uel/UEL9_VPDCL.for | `not_a_umat` |  |  |  |  |
| InstituteOfMechanics__Paraqus/examples/example_abaqus_extrusion_umat.f | `missing_material_data` |  |  |  |  |
| anics__Phase_Trafos_Carbon_Repartitioning/simulations/UMAT/umat_main.f | `external_dependency_unavailable` |  |  |  |  |
| momechanical_Gradient_Enhanced_Damage_UMAT/src/UMAT_DamThermMech_1_H.f | `transform_refused` |  |  |  |  |
| neral-shape-control-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Axe.for | `tangent_not_verified` | C3D8H | 0.00e+00 | 1.80e-06 | 0/2 |
| eral-shape-control-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Disk.for | `fully_verified` | C3D8H | 0.00e+00 | 1.18e-07 | 2/2 |
| l-shape-control-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Scallop.for | `primal_disagreed` | C3D8H | 5.86e-05 |  |  |
| pe-control-of-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-DupinCyclide.for | `primal_disagreed` | C3D8H | 1.10e-07 |  |  |
| al-shape-control-of-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-Genhel.for | `fully_verified` | C3D8H | 0.00e+00 | 2.40e-08 | 2/2 |
| al-shape-control-of-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-Saddle.for | `fully_verified` | C3D8H | 0.00e+00 | 8.56e-07 | 2/2 |
| ral-shape-control-of-shell/Abaqus_Files/3Dto3D/From-3D-to-3D-Petal.for | `primal_disagreed` | C3D8H | 9.10e-07 |  |  |
| -shape-control-of-shell/Abaqus_Files/3Dto3D/From-3D-to-3D-SeaShell.for | `primal_disagreed` | C3D8H | 2.00e-05 |  |  |
| neral-shape-control-of-shell/Abaqus_Files/Alex_Shocked/Growth-Alex.for | `primal_disagreed` | C3D8H | 0.00e+00 |  |  |
| General-shape-control-of-shell/Abaqus_Files/Beetle_Taxi/Growth-Car.for | `transformed_job_failed` | C3D8H |  |  |  |
| eneral-shape-control-of-shell/Abaqus_Files/FaceChange/Growth-Robot.for | `primal_disagreed` | C3D8H | 5.58e-01 |  |  |
| orces/Examples-In-Section-3/ArcDown/Th001/BodyForce-Growth-2Stages.for | `primal_disagreed` | C3D8H | 5.62e-08 |  |  |
| -Under-Body-Forces/Examples-In-Section-3/ArcDown/Th001/PureGravity.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| h-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th001/PureGrowth.for | `primal_disagreed` | C3D8H | 2.84e-09 |  |  |
| orces/Examples-In-Section-3/ArcDown/Th002/BodyForce-Growth-2Stages.for | `primal_disagreed` | C3D8H | 5.57e-08 |  |  |
| -Under-Body-Forces/Examples-In-Section-3/ArcDown/Th002/PureGravity.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| h-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th002/PureGrowth.for | `primal_disagreed` | C3D8H | 2.84e-09 |  |  |
| -In-Section-3/ArcDown/Th005-Visualization/BodyForce-Growth-2Stages.for | `primal_disagreed` | C3D8H | 5.56e-08 |  |  |
| orces/Examples-In-Section-3/ArcDown/Th005/BodyForce-Growth-2Stages.for | `primal_disagreed` | C3D8H | 5.56e-08 |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th005/PureGrowth.for | `primal_disagreed` | C3D8H | 2.84e-09 |  |  |
| Forces/Examples-In-Section-3/ArcDown/Th01/BodyForce-Growth-2Stages.for | `primal_disagreed` | C3D8H | 5.56e-08 |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th01/PureGravity.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| th-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th01/PureGrowth.for | `primal_disagreed` | C3D8H | 2.84e-09 |  |  |
| -Forces/Examples-In-Section-3/ArcUp/Th001/BodyForce-Growth-2Stages.for | `experiment_not_generated` | C3D8H |  |  |  |
| wth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th001/PureGrowth.for | `experiment_not_generated` | C3D8H |  |  |  |
| -Forces/Examples-In-Section-3/ArcUp/Th002/BodyForce-Growth-2Stages.for | `experiment_not_generated` | C3D8H |  |  |  |
| wth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th002/PureGrowth.for | `experiment_not_generated` | C3D8H |  |  |  |
| es-In-Section-3/ArcUp/Th005-Visualization/BodyForce-Growth-2Stages.for | `experiment_not_generated` | C3D8H |  |  |  |
| -Forces/Examples-In-Section-3/ArcUp/Th005/BodyForce-Growth-2Stages.for | `experiment_not_generated` | C3D8H |  |  |  |
| wth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th005/PureGrowth.for | `experiment_not_generated` | C3D8H |  |  |  |
| y-Forces/Examples-In-Section-3/ArcUp/Th01/BodyForce-Growth-2Stages.for | `experiment_not_generated` | C3D8H |  |  |  |
| wth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th01/PureGravity.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| owth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th01/PureGrowth.for | `experiment_not_generated` | C3D8H |  |  |  |
| y-Forces/Examples-In-Section-3/Flat/Th001/BodyForce-Growth-2Stages.for | `fully_verified` | C3D8H | 1.45e-12 | 6.31e-10 | 2/2 |
| owth-Under-Body-Forces/Examples-In-Section-3/Flat/Th001/PureGrowth.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| les-In-Section-3/Flat/Th002-Visualization/BodyForce-Growth-2Stages.for | `fully_verified` | C3D8H | 0.00e+00 | 6.31e-10 | 2/2 |
| y-Forces/Examples-In-Section-3/Flat/Th002/BodyForce-Growth-2Stages.for | `fully_verified` | C3D8H | 0.00e+00 | 6.31e-10 | 2/2 |
| owth-Under-Body-Forces/Examples-In-Section-3/Flat/Th002/PureGrowth.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| les-In-Section-3/Flat/Th005-Visualization/BodyForce-Growth-2Stages.for | `fully_verified` | C3D8H | 0.00e+00 | 6.31e-10 | 2/2 |
| y-Forces/Examples-In-Section-3/Flat/Th005/BodyForce-Growth-2Stages.for | `fully_verified` | C3D8H | 0.00e+00 | 6.31e-10 | 2/2 |
| wth-Under-Body-Forces/Examples-In-Section-3/Flat/Th005/PureGravity.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| owth-Under-Body-Forces/Examples-In-Section-3/Flat/Th005/PureGrowth.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| dy-Forces/Examples-In-Section-3/Flat/Th01/BodyForce-Growth-2Stages.for | `fully_verified` | C3D8H | 0.00e+00 | 6.31e-10 | 2/2 |
| rowth-Under-Body-Forces/Examples-In-Section-3/Flat/Th01/PureGrowth.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| orces/Examples-In-Section-3/HelixUp/Th001/BodyForce-Growth-2Stages.for | `primal_disagreed` | C3D8H | inf |  |  |
| -Under-Body-Forces/Examples-In-Section-3/HelixUp/Th001/PureGravity.for | `primal_disagreed` | C3D8H | inf |  |  |
| orces/Examples-In-Section-3/HelixUp/Th002/BodyForce-Growth-2Stages.for | `primal_disagreed` | C3D8H | inf |  |  |
| -Under-Body-Forces/Examples-In-Section-3/HelixUp/Th002/PureGravity.for | `primal_disagreed` | C3D8H | inf |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/HelixUp/Th002/PureGrowth.for | `primal_disagreed` | C3D8H | inf |  |  |
| orces/Examples-In-Section-3/HelixUp/Th005/BodyForce-Growth-2Stages.for | `primal_disagreed` | C3D8H | inf |  |  |
| -Under-Body-Forces/Examples-In-Section-3/HelixUp/Th005/PureGravity.for | `primal_disagreed` | C3D8H | inf |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/HelixUp/Th005/PureGrowth.for | `primal_disagreed` | C3D8H | inf |  |  |
| Forces/Examples-In-Section-3/HelixUp/Th01/BodyForce-Growth-2Stages.for | `primal_disagreed` | C3D8H | inf |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/HelixUp/Th01/PureGravity.for | `primal_disagreed` | C3D8H | inf |  |  |
| Examples-In-Section-3/ParabolicDown/Th001/BodyForce-Growth-2Stages.for | `experiment_not_generated` | C3D8H |  |  |  |
| -Body-Forces/Examples-In-Section-3/ParabolicDown/Th001/PureGravity.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| Examples-In-Section-3/ParabolicDown/Th002/BodyForce-Growth-2Stages.for | `experiment_not_generated` | C3D8H |  |  |  |
| r-Body-Forces/Examples-In-Section-3/ParabolicDown/Th002/PureGrowth.for | `primal_disagreed` | C3D8H | 2.34e-10 |  |  |
| Examples-In-Section-3/ParabolicDown/Th005/BodyForce-Growth-2Stages.for | `experiment_not_generated` | C3D8H |  |  |  |
| -Body-Forces/Examples-In-Section-3/ParabolicDown/Th005/PureGravity.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| er-Body-Forces/Examples-In-Section-3/ParabolicDown/Th01/PureGrowth.for | `primal_disagreed` | C3D8H | 2.34e-10 |  |  |
| der-Body-Forces/Examples-In-Section-3/ParabolicUp/Th001/PureGrowth.for | `experiment_not_generated` | C3D8H |  |  |  |
| der-Body-Forces/Examples-In-Section-3/ParabolicUp/Th002/PureGrowth.for | `experiment_not_generated` | C3D8H |  |  |  |
| es/Examples-In-Section-3/ParabolicUp/Th01/BodyForce-Growth-2Stages.for | `fully_verified` | C3D8H | 1.87e-12 | 3.60e-09 | 2/2 |
| ples-In-Section-4/Experiment-DRAGONSKIN20-ArcDown/Th01/PureGravity.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| mples-In-Section-4/Experiment-DRAGONSKIN20-ArcDown/Th01/PureGrowth.for | `primal_disagreed` | C3D8H | 1.30e-07 |  |  |
| xamples-In-Section-4/Experiment-DRAGONSKIN20-Flat/Th005/PureGrowth.for | `transformed_job_failed` | C3D8H |  |  |  |
| Examples-In-Section-4/Experiment-DRAGONSKIN20-Flat/Th01/PureGrowth.for | `experiment_not_generated` | C3D8H |  |  |  |
| ples-In-Section-4/Experiment-ECOFLEX0030-ArcDown/Th005/PureGravity.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| mples-In-Section-4/Experiment-ECOFLEX0030-ArcDown/Th01/PureGravity.for | `fully_verified` | C3D8H | 0.00e+00 | 1.59e-10 | 2/2 |
| ction-4/Experiment-ECOFLEX0030-Flat/Th005/BodyForce-Growth-2Stages.for | `transformed_job_failed` | C3D8H |  |  |  |
| Examples-In-Section-4/Experiment-ECOFLEX0030-Flat/Th005/PureGrowth.for | `transformed_job_failed` | C3D8H |  |  |  |
| ection-4/Experiment-ECOFLEX0030-Flat/Th01/BodyForce-Growth-2Stages.for | `fully_verified` | C3D8H | 1.85e-12 | 6.95e-10 | 2/2 |
| dy-Forces/PathSensitivity/Th001-1MPa/BodyForce-Growth-GravityFirst.for | `experiment_not_generated` | C3D8H |  |  |  |
| dy-Forces/PathSensitivity/Th001-5MPa/BodyForce-Growth-Simultaneous.for | `experiment_not_generated` | C3D8H |  |  |  |
| rface-conformal-mappings/Analytical_Example/2D/inputFile/Growth-EX.for | `fully_verified` | C3D8H | 1.16e-06 | 5.82e-11 | 2/2 |
| rface-conformal-mappings/Analytical_Example/2D/inputFile/Growth-Z2.for | `fully_verified` | C3D8H | 6.49e-05 | 5.82e-11 | 2/2 |
| ace-conformal-mappings/Analytical_Example/2D/inputFile/Growth-frac.for | `fully_verified` | C3D8H | 2.84e-05 | 5.82e-11 | 2/2 |
| -conformal-mappings/Analytical_Example/3D/InputFile/Growth-MinSur1.for | `tangent_not_verified` | C3D8H | 0.00e+00 | 5.80e-05 | 0/2 |
| -conformal-mappings/Analytical_Example/3D/InputFile/Growth-MinSur2.for | `fully_verified` | C3D8H | 0.00e+00 | 1.55e-07 | 2/2 |
| -conformal-mappings/Analytical_Example/3D/InputFile/Growth-MinSur3.for | `fully_verified` | C3D8H | 0.00e+00 | 5.82e-11 | 2/2 |
| mal-mappings/Analytical_Example/3D/MMAFile/Example1/Growth-MinSur1.for | `tangent_not_verified` | C3D8H | 0.00e+00 | 1.33e-06 | 1/2 |
| mal-mappings/Analytical_Example/3D/MMAFile/Example2/Growth-MinSur2.for | `fully_verified` | C3D8H | 0.00e+00 | 1.76e-08 | 2/2 |
| pings/Analytical_Example/3D/MMAFile/Example3-Sphere/Growth-MinSur3.for | `fully_verified` | C3D8H | 0.00e+00 | 5.82e-11 | 2/2 |
| ppings/Analytical_Example/3D/MMAFile/Example4-Torus/Growth-MinSur3.for | `fully_verified` | C3D8H | 0.00e+00 | 5.82e-11 | 2/2 |
| ace-conformal-mappings/Bunny/Part1/ABAQUS_files/Growth-Bunny-Part1.for | `original_job_failed` | C3D8H |  |  |  |
| ace-conformal-mappings/Bunny/Part2/ABAQUS_files/Growth-Bunny-Part2.for | `original_job_failed` | C3D8H |  |  |  |
| face-conformal-mappings/Hunman_face/ABAQUS_files/Growth-Human-face.for | `original_job_failed` | C3D8H |  |  |  |
| -and-surface-conformal-mappings/Instability_Analysis/Growth-Sphere.for | `fully_verified` | C3D8H | 0.00e+00 | 5.82e-11 | 2/2 |
| urface-conformal-mappings/Mesh_Convergence_test/2D/EX/10/Growth-EX.for | `fully_verified` | C3D8H | 2.36e-07 | 5.82e-11 | 2/2 |
| ce-conformal-mappings/Mesh_Convergence_test/2D/Frac/10/Growth-Frac.for | `fully_verified` | C3D8H | 2.84e-05 | 5.82e-11 | 2/2 |
| urface-conformal-mappings/Mesh_Convergence_test/2D/Z2/10/Growth-Z2.for | `fully_verified` | C3D8H | 6.49e-05 | 5.82e-11 | 2/2 |
| rmal-mappings/Mesh_Convergence_test/3D/Catenoid/10/Growth-Catenoid.for | `fully_verified` | C3D8H | 0.00e+00 | 1.55e-07 | 2/2 |
| rmal-mappings/Mesh_Convergence_test/3D/Helicoid/10/Growth-Helicoid.for | `tangent_not_verified` | C3D8H | 0.00e+00 | 5.80e-05 | 0/2 |
| onformal-mappings/Mesh_Convergence_test/3D/Sphere/10/Growth-Sphere.for | `fully_verified` | C3D8H | 0.00e+00 | 5.82e-11 | 2/2 |
| ce-conformal-mappings/Mesh_Convergence_test/Alex/20470/Growth-Alex.for | `primal_disagreed` | C3D8H | 1.56e+00 |  |  |
| face-conformal-mappings/Mesh_Convergence_test/Alex/749/Growth-Alex.for | `primal_disagreed` | C3D8H | 1.52e+00 |  |  |
| surface-conformal-mappings/Model_car/ABAQUS_files/Growth-Model-car.for | `original_job_failed` | C3D8H |  |  |  |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE1.for | `fully_verified` | C3D8 | 0.00e+00 | 4.14e-11 | 2/2 |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE2.for | `fully_verified` | C3D8 | 5.95e-06 | 4.15e-11 | 2/2 |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE3.for | `primal_disagreed` | C3D8 | 4.10e-06 |  |  |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE1.for | `fully_verified` | C3D8 | 1.62e-06 | 4.15e-11 | 2/2 |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE2.for | `fully_verified` | C3D8 | 1.87e-06 | 4.14e-11 | 2/2 |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE3.for | `fully_verified` | C3D8 | 3.14e-07 | 4.15e-11 | 2/2 |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE1.for | `fully_verified` | C3D8 | 4.16e-08 | 4.14e-11 | 2/2 |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE2.for | `primal_disagreed` | C3D8 | 5.32e-06 |  |  |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE3.for | `fully_verified` | C3D8 | 4.10e-07 | 4.15e-11 | 2/2 |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE4.for | `fully_verified` | C3D8 | 4.88e-07 | 4.15e-11 | 2/2 |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE5.for | `primal_disagreed` | C3D8 | 1.26e-01 |  |  |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE6.for | `fully_verified` | C3D8 | 6.21e-07 | 4.14e-11 | 2/2 |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-101.for | `experiment_not_generated` | C3D8H |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-102.for | `experiment_not_generated` | C3D8H |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-103.for | `experiment_not_generated` | C3D8H |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-11.for | `experiment_not_generated` | C3D8H |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-12.for | `experiment_not_generated` | C3D8H |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-13.for | `experiment_not_generated` | C3D8H |  |  |  |
| Jeff97__growth-of-shell/Input files and UMAT/Example1/SweetMelon.for | `primal_disagreed` | C3D8H | 9.51e-03 |  |  |
| Jeff97__growth-of-shell/Input files and UMAT/Example2/MorningGlory.for | `fully_verified` | C3D8H | 1.55e-05 | 1.91e-08 | 2/2 |
| Jeff97__growth-of-shell/Input files and UMAT/Example3/Trachea.for | `tangent_not_verified` | C3D8H | 3.45e-06 | 3.93e-06 | 0/2 |
| Jeff97__growth-of-shell/Input files and UMAT/Example4/Apple.for | `fully_verified` | C3D8H | 1.19e-06 | 1.60e-07 | 2/2 |
| owth-of-shell/Input files and UMAT/Example5/CereusForbesiiSpiralis.for | `primal_disagreed` | C3D8H | 4.67e-05 |  |  |
| 97__growth-of-shell/Input files and UMAT/Example6/TendrilOfPumpkin.for | `original_job_failed` | C3D8H |  |  |  |
| JuliaFEM__UMAT.jl/umat_models/drucker_prager_plasticity.f90 | `transform_refused` |  |  |  |  |
| JuliaFEM__UMAT.jl/umat_models/gurson_porous_plasticity.f90 | `transform_refused` |  |  |  |  |
| KianAbd__vCANN_FEM/Abaqus/umat.f90 | `transform_refused` |  |  |  |  |
| KianAbd__vCANN_FEM/Abaqus/umat_vCANN.f90 | `missing_material_data` |  |  |  |  |
| KianAbd__vCANN_FEM/Abaqus/umat_vCANN.for | `missing_material_data` |  |  |  |  |
| FEM/TensorFlow/Results_Liao_Thermo/20260601-103627/UMAT/umat_vCANN.for | `missing_material_data` |  |  |  |  |
| KnutAM__MaterialModels/models/CrystalPlasticity/src/taylor_model.f90 | `transform_refused` |  |  |  |  |
| tAM__MaterialModels/models/GenFiniteStrain/src/GeneralFiniteStrain.for | `external_dependency_unavailable` |  |  |  |  |
| nutAM__MaterialModels/models/GenSmallStrain/src/GeneralSmallStrain.f90 | `transform_refused` |  |  |  |  |
| KnutAM__MaterialModels/models/MM2021/src/umat.f90 | `transform_refused` |  |  |  |  |
| KnutAM__MaterialModels/models/Qin2018/src/umat.f90 | `transform_refused` |  |  |  |  |
| LallyLabTCD__localBasisAbaqus/Case studies/umat_MA_global.for | `transform_refused` |  |  |  |  |
| LallyLabTCD__localBasisAbaqus/Case studies/umat_MA_local.for | `transform_refused` |  |  |  |  |
| esson C - fibre reinforced anistropic models/Abaqus/umat_MA_global.for | `transform_refused` |  |  |  |  |
| Lesson C - fibre reinforced anistropic models/Abaqus/umat_MA_local.for | `transform_refused` |  |  |  |  |
| MCM-QMUL__PhaseFieldComp/Subroutine/UELUMATPhaseField_AT2.for | `transformed_job_failed` | C3D8 |  |  |  |
| PeriDoX__PeriDoX/Publications/2022_JOSS/data/UMAT/base.f | `missing_material_data` |  |  |  |  |
| PeriHub__PeriLab.jl/src/Models/Material/UMATs/base.f | `missing_material_data` |  |  |  |  |
| PeriHub__PeriLab.jl/src/Models/Material/UMATs/usertest.f | `transform_refused` |  |  |  |  |
| titutiveModels/fortran_models/linear_elastic/UMAT_LinearElasticity.f90 | `missing_material_data` |  |  |  |  |
| tes__ConstitutiveModels/fortran_models/mohr_coulomb/UMAT_MohrCoulomb.f | `missing_material_data` |  |  |  |  |
| RafalMichalczyk__PavementDesign/Subroutines/umat_gmaxwell.for | `missing_material_data` |  |  |  |  |
| RafalMichalczyk__PavementDesign/Subroutines/umat_ms_plast.for | `missing_material_data` |  |  |  |  |
| ReachOptimum__mlpcp-interp-dic/abaqus/UMMDp_FLC.f | `transform_refused` |  |  |  |  |
| RickAlb__UMAT-DFD-Lebedev/all_subroutines/UMAT_DFD_LEB.for | `transform_refused` |  |  |  |  |
| RitioL__PolyFatigueCrackSim/CPFEM-val/subroutines_revised.for | `primal_disagreed` | CPE4 | 1.87e+00 |  |  |
| RitioL__PolyFatigueCrackSim/workplace/huang_umat_97.for | `primal_disagreed` | CPE4 | 1.88e+00 |  |  |
| RitioL__PolyFatigueCrackSim/workplace/subroutines3_revised.for | `primal_disagreed` | CPE4 | 1.87e+00 |  |  |
| __DIC2ABAQUS/OXFORD-UMAT/Example - Polycrytal with PROPS/OXFORD-UMAT.f | `transform_refused` |  |  |  |  |
| n__DIC2ABAQUS/OXFORD-UMAT/Example - Residual deformation/OXFORD-UMAT.f | `transform_refused` |  |  |  |  |
| Shi2oon__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v2.26/OXFORD-UMAT.f | `transform_refused` |  |  |  |  |
| Shi2oon__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v3.1/OXFORD-UMAT.f | `transform_refused` |  |  |  |  |
| Shi2oon__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v3.3/OXFORD-UMAT.f | `transform_refused` |  |  |  |  |
| Sina-Taghizadeh__UMAT_Hyperelastic/CompresibleNeoHookean.for | `fully_verified` | C3D8 | 0.00e+00 | 8.62e-10 | 2/2 |
| Woowinehouse__ABQ-UMAT-Sanisand-High/src/interface/umat.f90 | `transform_refused` |  |  |  |  |
| Woowinehouse__Abaqus_UMAT_sanisand/merge/source.F90 | `missing_material_data` |  |  |  |  |
| Woowinehouse__Abaqus_UMAT_sanisand/src/interface/umat.f90 | `transform_refused` |  |  |  |  |
| orlthen__20220314-abqus-simulation/abaqus/enhanced/enhanced_curing.for | `transformed_job_failed` | C3D8 |  |  |  |
| __20220314-abqus-simulation/abaqus/original/array_with_two_pixel_z.for | `original_job_failed` | C3D8 |  |  |  |
| hen__20220314-abqus-simulation/abaqus/simplified/simplified_curing.for | `primal_disagreed` | C3D8 | inf |  |  |
| Yutu0k__ABQflow/examples/07_SubroutineJob/subroutine/umat_elastic.for | `missing_material_data` |  |  |  |  |
| abuganza__BayesianCalibrationSkinGrowth/GOH_Example.f | `transformed_job_failed` | C3D8 |  |  |  |
| abuganza__BayesianCalibrationSkinGrowth/Iso_Example.f | `derivative_truncated` | C3D8 | 0.00e+00 |  |  |
| librationSkinGrowth/Revision/Abaqus SImulation/GOH/BC1_50cc/GOH_50cc.f | `transformed_job_failed` | C3D8 |  |  |  |
| librationSkinGrowth/Revision/Abaqus SImulation/GOH/BC1_55cc/GOH_55cc.f | `transformed_job_failed` | C3D8 |  |  |  |
| ionSkinGrowth/Revision/Abaqus SImulation/Isotropic/BC1_50cc/Iso_50cc.f | `derivative_truncated` | C3D8 | 0.00e+00 |  |  |
| ionSkinGrowth/Revision/Abaqus SImulation/Isotropic/BC1_60cc/Iso_60cc.f | `derivative_truncated` | C3D8 | 0.00e+00 |  |  |
| ionSkinGrowth/Revision/Abaqus SImulation/Isotropic/BC2_60cc/Iso_60cc.f | `derivative_truncated` | C3D8 | 0.00e+00 |  |  |
| onSkinGrowth/Revision/Abaqus SImulation/SampleSimulation/GOH_Example.f | `transformed_job_failed` | C3D8 |  |  |  |
| onSkinGrowth/Revision/Abaqus SImulation/SampleSimulation/Iso_Example.f | `derivative_truncated` | C3D8 | 0.00e+00 |  |  |
| abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_strain.f | `primal_disagreed` | CPE4 | 1.43e-06 |  |  |
| abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_stress.f | `derivative_truncated` | CPS4 | 0.00e+00 |  |  |
| abuganza__UMAT_anisotropic_damage/UMAT_Tissue_3d.f | `primal_disagreed` | C3D8 | 7.01e-06 |  |  |
| adtzlr__ttb/docs/examples/Abaqus/umat_nh_ttb.f | `transform_refused` |  |  |  |  |
| adtzlr__ttb/docs/examples/Abaqus/umat_nh_ttb_simple.f | `transform_refused` |  |  |  |  |
| adtzlr__ttb/docs/examples/script_umat.f | `not_a_umat` |  |  |  |  |
| ahartloper__UVC_MatMod/Abaqus/UVCmultiaxial.for | `transform_refused` |  |  |  |  |
| ahartloper__UVC_MatMod/Abaqus/UVCplanestress.for | `original_job_failed` | CPS4 |  |  |  |
| ahartloper__UVC_MatMod/Abaqus/UVCuniaxial.for | `transform_refused` |  |  |  |  |
| ahartloper__UVC_MatMod/Abaqus/UVCuniaxial_IS.for | `transform_refused` |  |  |  |  |
| artorg-unibe-ch__HFE/02_CODE/abq/UMAT_BIPHASIC.f | `missing_material_data` |  |  |  |  |
| ge-UMAT-Public/HETVAL_nonLocalLemaitre/HETVAL_lemaitreDamageNonLocal.f | `primal_disagreed` | CPS4 | 0.00e+00 |  |  |
| _Lemaitre-damage-UMAT-Public/nonLocalLemaitre/lemaitreDamageNonLocal.f | `fully_verified` | CPS4 | 0.00e+00 | 8.72e-16 | 2/2 |
| MechanicalFoam/abaqusUMATs/abaqusUmatMohrCoulomb/MohrCoulombAbaqus.for | `transform_refused` |  |  |  |  |
| bennifuchs__TsaiWu-Fortran/abaqus-umat-interface.f90 | `transform_refused` |  |  |  |  |
| bennifuchs__TsaiWu-Fortran/umat.f90 | `transform_refused` |  |  |  |  |
| m_simulate/abaqus/scriptbase/benchmark_abaqus_scripts/veni_mix_model.f | `transform_refused` |  |  |  |  |
| imulate/abaqus/scriptbase/benchmark_abaqus_scripts/vevp_leonov_model.f | `missing_material_data` |  |  |  |  |
| _simulate/abaqus/scriptbase/benchmark_abaqus_scripts/vp_leonov_model.f | `missing_material_data` |  |  |  |  |
| bmmbUPF__abaqusIVD/Sub_MechDisc.f | `external_dependency_unavailable` |  |  |  |  |
| bmmbUPF__abaqusIVD/Sub_TransDisc.f | `external_dependency_unavailable` |  |  |  |  |
| brizzer__elmerfem_piezo/fem/src/modules/ElasticSolve.F90 | `not_a_umat` |  |  |  |  |
| calculix__ccx_fff/src/umat.f | `missing_material_data` |  |  |  |  |
| compas-dev__compas_fea2/data/umat/umat-hooke-iso.f | `missing_material_data` |  |  |  |  |
| compas-dev__compas_fea2/data/umat/umat-hooke-transversaliso.f | `missing_material_data` |  |  |  |  |
| core-marine-dev__elmerfem/fem/src/modules/ElasticSolve.F90 | `not_a_umat` |  |  |  |  |
| cunhuav__Abaqus-Neural-Network-UMAT/ro_nn_umat.f90 | `transform_refused` |  |  |  |  |
| damin225__short-crack-propagation-3d/input_clean/umat.f | `transform_refused` |  |  |  |  |
| davidmorinNTNU__ABAQUS_subroutines/V_UMAT/UMAT.f | `transform_refused` |  |  |  |  |
| ekurth__NEML/util/abaqus/nemlumat.f | `transform_refused` |  |  |  |  |
| frodal__SCMM-hypo/HypoImp.f | `external_dependency_unavailable` |  |  |  |  |
| glu46__3D_anisotropic_viscoelastic_model/OrthoWoodCreep_Column.for | `missing_material_data` |  |  |  |  |
| glu46__3D_anisotropic_viscoelastic_model/OrthoWoodCreep_General.for | `missing_material_data` |  |  |  |  |
| glu46__3D_anisotropic_viscoelastic_model/Ortho_WoodCreep_Cube.for | `missing_material_data` |  |  |  |  |
| glu46__3D_anisotropic_viscoelastic_model/TIRockCreep_CANEY.for | `missing_material_data` |  |  |  |  |
| glu46__3D_anisotropic_viscoelastic_model/TIRockCreep_GENERAL.for | `missing_material_data` |  |  |  |  |
| hamza-djeloud__thesis_project/plate_with_notch.for | `fully_verified` | CPS4 | 0.00e+00 |  | 3/4 |
| harshaa765__Bilinear-CZM-UMAT/Bilinear_CZM_UMAT.for | `unsupported_formulation` |  |  |  |  |
| harshaa765__UMATFile/UMAT.for | `transform_refused` |  |  |  |  |
| hwu12sluedu__MaterialAI-Workbench/examples/UMAT/ml_umat.f | `transform_refused` |  |  |  |  |
| u__MaterialAI-Workbench/material_ai_workbench/resources/umat/ml_umat.f | `transform_refused` |  |  |  |  |
| ibf-RWTH__GA-Calibration/subroutine/Umat_CP.for | `transform_refused` |  |  |  |  |
| irfancn__Abaqus-UEL-elastic/uel_elastic.for | `original_job_failed` | CPS4 |  |  |  |
| irfancn__Abaqus-UMAT-elastic/umat_elastic.for | `fully_verified` | C3D8 | 0.00e+00 | 1.00e-14 | 4/4 |
| irfancn__Abaqus-UMAT-viscoelastic/umat_viscoelastic.for | `fully_verified` | C3D8 | 6.50e-05 | 1.00e-14 | 4/4 |
| j-machacek__numgeo-hardening-soil-bricks/src/hs-bricks-umat/umat.f90 | `transform_refused` |  |  |  |  |
| umgeo-hardening-soil-bricks/src/incremental-driver/material_models.f90 | `transform_refused` |  |  |  |  |
| j-machacek__numgeo-hypo-igs-isa-gis/src/material_models.f90 | `transform_refused` |  |  |  |  |
| jacojvr__UMATs/UMAT_framework/umat_comb.f | `transform_refused` |  |  |  |  |
| jacojvr__UMATs/UMAT_framework/umat_iso.f | `transform_refused` |  |  |  |  |
| baqus_subroutine_skills/official_examples/umat/umat_elastic_official.f | `original_job_failed` | C3D8 |  |  |  |
| routine_skills/official_examples/umat/umat_mises_plasticity_official.f | `missing_material_data` |  |  |  |  |
| jcmcmurry__pipelining/elmerfem/fem/src/modules/ElasticSolve.F90 | `external_dependency_unavailable` |  |  |  |  |
| jgomezc1__ABAQUS-US/INPUT_FILES/UEL8_ECL_AXY.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/SAMPLE/UEL9_VPDCO.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL8_ECL.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL8_ECO.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL8_PCLI.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL8_PCLI_R.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL8_PCLK.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL8_PCOI.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL8_PCOR.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL8_PCOR_KIN.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL8_VPDCL.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL8_VPDCO.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_ECL.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_ECO.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_ECO_m.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_PCLI.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_PCLI_R.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_PCLK.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_PCOI.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_PCON.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_PCOR.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_PCOR_KIN.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_VPDCL.for | `not_a_umat` |  |  |  |  |
| jgomezc1__ABAQUS-US/UELS/UEL9_VPDCL_R.for | `not_a_umat` |  |  |  |  |
| jgomezc1__DRM-FEAP/matutil.for | `not_a_umat` |  |  |  |  |
| jgomezc1__WAVES/SOURCE/matutil.for | `not_a_umat` |  |  |  |  |
| jpsferreira__UMAT-ABAQUS/src/_umat.for | `transform_refused` |  |  |  |  |
| jpsferreira__UMAT-ABAQUS/test_in_abaqus/umat_general.for | `transform_refused` |  |  |  |  |
| jpsferreira__UMAT-ABAQUS/umat_general.for | `transform_refused` |  |  |  |  |
| keisuke58__pde-fem-biofilm/umat_biofilm_visco.f | `transform_refused` |  |  |  |  |
| keisuke58__pde-fem-biofilm/umat_biofilm_visco_2ch.f | `support_build_failed` | C3D8 |  |  |  |
| keisuke58__pde-fem-biofilm/umat_biofilm_visco_phase2.f | `tangent_not_verified` | C3D8 | 0.00e+00 | 3.21e-02 | 0/2 |
| learnitmyway__Paperboard/Fortran/umat.f90 | `not_a_umat` |  |  |  |  |
| llnl__ExaConstit/src/umats/umat.f | `transform_refused` |  |  |  |  |
| aqus6.14-5-UMAT-constative-model/Duncan-Chang_EB_UMAT_ABAQUS6.14-5.for | `transform_refused` |  |  |  |  |
| it__thesis-benchmark-cases/Benchmarks/Fuel_pellet_quarter/czmHealing.f | `unsupported_formulation` |  |  |  |  |
| it__thesis-benchmark-cases/Benchmarks/Notched_plate_shear/czmHealing.f | `unsupported_formulation` |  |  |  |  |
| luisez1988__Viscoplastic-NorSand/UMAT_Nor_Sand_Zamb.for | `transform_refused` |  |  |  |  |
| luisez1988__Viscoplastic-SSMC/UMAT_SSMCWStrainRates_Zambrano.for | `incomplete_or_corrupt_source` |  |  |  |  |
| luisez1988__Viscoplastic_MC_coupled/UMAT_MCWStrainRates_Zambrano.for | `incomplete_or_corrupt_source` |  |  |  |  |
| makkemal__NGIMASEM/usermat.F | `not_a_umat` |  |  |  |  |
| marioruiarruda__Hashin_2D_UMAT/umat_hashin_f90.f90 | `transform_refused` |  |  |  |  |
| marioruiarruda__Hashin_3D_UMAT/umat_hashin3D_f90.f90 | `transform_refused` |  |  |  |  |
| marioruiarruda__Mazars_UMAT/umat_mazars_f90.f90 | `transform_refused` |  |  |  |  |
| marioruiarruda__Tsai-Wu_2D_UMAT/umat_tsaiwu_f90.f90 | `transform_refused` |  |  |  |  |
| matmodlab__matmodlab2/matmodlab2/umat/uhyper_wrap.f90 | `transform_refused` |  |  |  |  |
| matmodlab__matmodlab2/matmodlab2/umat/umats/umat_neohooke.f90 | `missing_material_data` |  |  |  |  |
| matmodlab__matmodlab2/matmodlab2/umat/umats/umat_stub.f90 | `transform_refused` |  |  |  |  |
| matmodlab__matmodlab2/matmodlab2/umat/umats/umat_thermoelastic.f90 | `missing_material_data` |  |  |  |  |
| mauroarcidiacono__Crystal-Plasticity-UMAT/umat_abaqus.for | `external_dependency_unavailable` |  |  |  |  |
| mauroarcidiacono__Crystal-Plasticity-UMAT/umat_standalone.for | `external_dependency_unavailable` |  |  |  |  |
| olla__BMMB24/simulations/input files/umat_transverseIsotropicStretch.f | `fully_verified` | C3D8 | 0.00e+00 | 4.62e-08 | 2/2 |
| mholla__SOFT24/simulations/UMAT_axon_tension.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_area_morph.f | `fully_verified` | C3D8 | 0.00e+00 | 9.43e-11 | 2/2 |
| mholla__growth/umats/umat_area_morph_Abaqus.f | `experiment_not_generated` | C3D8 |  |  |  |
| mholla__growth/umats/umat_area_morph_orient.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_area_stretch.f | `fully_verified` | C3D8 | 0.00e+00 | 1.24e-10 | 2/2 |
| mholla__growth/umats/umat_fiber_morph.f | `fully_verified` | C3D8 | 0.00e+00 | 8.91e-11 | 2/2 |
| mholla__growth/umats/umat_fiber_morph_Abaqus.f | `experiment_not_generated` | C3D8 |  |  |  |
| mholla__growth/umats/umat_fiber_morph_orient.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_fiber_stretch.f | `fully_verified` | C3D8 | 0.00e+00 | 1.24e-10 | 2/2 |
| mholla__growth/umats/umat_iso_Mandel.f | `fully_verified` | C3D8 | 0.00e+00 | 1.24e-10 | 2/2 |
| mholla__growth/umats/umat_iso_Mandel_v2.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_iso_morph.f | `fully_verified` | C3D8 | 0.00e+00 | 9.16e-11 | 2/2 |
| mholla__growth/umats/umat_iso_morph_Abaqus.f | `experiment_not_generated` | C3D8 |  |  |  |
| mholla__growth/umats/umat_iso_stretch.f | `fully_verified` | C3D8 | 0.00e+00 | 1.24e-10 | 2/2 |
| mholla__growth/umats/umat_neohooke.f | `incomplete_or_corrupt_source` | C3D8 |  |  |  |
| mholla__growth/umats/umat_neohooke_abaqus.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_ortho_stretch.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_transverse.f | `fully_verified` | C3D8 | 0.00e+00 | 1.24e-10 | 2/2 |
| n Code_Basic_Viscoelasticity/ABAQUS_DSR_EXAMPLE/ViscoelasticityCode3.f | `transform_refused` |  |  |  |  |
| scoelastictiy/Fortran Code_Basic_Viscoelasticity/ViscoelasticityCode.f | `incomplete_or_corrupt_source` |  |  |  |  |
| coelastictiy/Fortran Code_Basic_Viscoelasticity/ViscoelasticityCode2.f | `incomplete_or_corrupt_source` |  |  |  |  |
| coelastictiy/Fortran Code_Basic_Viscoelasticity/ViscoelasticityCode3.f | `incomplete_or_corrupt_source` |  |  |  |  |
| tictiy/Linking Mechanical with Aging Code/CoupledMechanicalAgingCode.f | `incomplete_or_corrupt_source` |  |  |  |  |
| ictiy/Linking Mechanical with Aging Code/CoupledMechanicalAgingCode2.f | `incomplete_or_corrupt_source` |  |  |  |  |
| mrkearden__abaqus_umat/ElasticSolve.F90 | `external_dependency_unavailable` |  |  |  |  |
| mrkearden__abaqus_umat/PlasticSolve.F90 | `not_a_umat` |  |  |  |  |
| mrkearden__abaqus_umat/UMAT.F90 | `external_dependency_unavailable` |  |  |  |  |
| grilli__Oxford_Crystal_Plasticity/ExampleInputFiles/HCPnoTwin/umat.for | `external_dependency_unavailable` |  |  |  |  |
| nsundar__PFM_UMAT_ElastoPlastic/UMAT_phasefield_plasticity.f | `incomplete_or_corrupt_source` | CPS4 |  |  |  |
| aubach__abaqus-explicit/examples/_pile_driving/HPP_Staubach_explicit.f | `transform_refused` |  |  |  |  |
| patrickstaubach__abaqus-explicit/src/HPP_Staubach_explicit.f | `transform_refused` |  |  |  |  |
| peer-open-source__xara/SRC/domain/peri/umat.for | `external_dependency_unavailable` |  |  |  |  |
| phhannequart__UMAT_sma_hannequart/UMAT_sma_hannequart.for | `missing_material_data` |  |  |  |  |
| stic/src/abaqusUMATs/abaqusUmatLinearElastic/abaqusUmatLinearElastic.f | `incomplete_or_corrupt_source` |  |  |  |  |
| la__ferrite-fortran-integration_using_Julia/src/Material_Models/umat.f | `transform_refused` |  |  |  |  |
| rhdodds__warp3d/src/user_routines_umat.f | `not_a_umat` |  |  |  |  |
| MAT - Strain-based Return Mapping - Fully-Implicit/umat_subroutine.for | `transform_refused` |  |  |  |  |
| UMAT - Strain-based Return Mapping - Semi-Implicit/umat_subroutine.for | `transform_refused` |  |  |  |  |
| MAT - Stress-based Return Mapping - Fully-Implicit/umat_subroutine.for | `transform_refused` |  |  |  |  |
| UMAT - Stress-based Return Mapping - Semi-Implicit/umat_subroutine.for | `transform_refused` |  |  |  |  |
| i__Tahoe/development/src/elements/solid/materials/ABAQUS_BCJ/bcj_iso.f | `incomplete_or_corrupt_source` |  |  |  |  |
| sas229__geomat/src/umat/src/umat.f90 | `transform_refused` |  |  |  |  |
| sas229__geomat/tests/umat_integration.f90 | `transform_refused` |  |  |  |  |
| sd104400__OPA_Modeling/FE Modeling/UMAT_DPIsodwAniDM.for | `transform_refused` |  |  |  |  |
| seekzzh__mat-model-lab/assets/templates/abaqus_umat.f | `missing_material_data` |  |  |  |  |
| shayansss__bioumat/SUBROUTINES.FOR | `missing_material_data` |  |  |  |  |
| shayansss__hml/NONLIPLS.for | `missing_material_data` |  |  |  |  |
| simoneponcioni__HFE/02_CODE/abq/UMAT_BIPHASIC.f | `missing_material_data` |  |  |  |  |
| swayli94__AbaqusTools/LaRC05/umat.f90 | `transform_refused` |  |  |  |  |
| tengzhang48__CoupFE/examples/neo_hookean_umat/neo_hookean_umat.for | `transform_refused` |  |  |  |  |
| tengzhang48__CoupFE/examples/ogden_umat/ogden_umat.for | `transform_refused` |  |  |  |  |
| tengzhang48__CoupFE/examples/small_strain_j2_umat/small_strain_j2.for | `transform_refused` |  |  |  |  |
| /examples/small_strain_viscoelastic_umat/small_strain_viscoelastic.for | `transform_refused` |  |  |  |  |
| tengzhang48__abaqus_ufl/examples/_template/template_umat.for | `transform_refused` |  |  |  |  |
| tengzhang48__abaqus_ufl/examples/neo_hookean_umat/neo_hookean_umat.for | `transform_refused` |  |  |  |  |
| tengzhang48__abaqus_ufl/examples/ogden_umat/ogden_umat.for | `transform_refused` |  |  |  |  |
| gzhang48__abaqus_ufl/examples/small_strain_j2_umat/small_strain_j2.for | `transform_refused` |  |  |  |  |
| /examples/small_strain_viscoelastic_umat/small_strain_viscoelastic.for | `transform_refused` |  |  |  |  |
| thealanjason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_1EL.for | `transformed_job_failed` | C3D8H |  |  |  |
| thealanjason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_2EL.for | `transformed_job_failed` | C3D8H |  |  |  |
| thealanjason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_3EL.for | `transformed_job_failed` | C3D8H |  |  |  |
| njason__umat_finite_viscoelasticity/report/chapters/VISC_OGDEN_2EL.for | `incomplete_or_corrupt_source` | C3D8H |  |  |  |
| _umat_finite_viscoelasticity/simulation_input_files/VISC_OGDEN_1EL.for | `incomplete_or_corrupt_source` | C3D8H |  |  |  |
| _umat_finite_viscoelasticity/simulation_input_files/VISC_OGDEN_2EL.for | `incomplete_or_corrupt_source` | C3D8H |  |  |  |
| _umat_finite_viscoelasticity/simulation_input_files/VISC_OGDEN_3EL.for | `incomplete_or_corrupt_source` | C3D8H |  |  |  |
| thelfer__tfel/mtest/tests/mtest/castem/umat.f | `transform_refused` |  |  |  |  |
| sy__UMAT_optimization_public/UMAT_U2_OPTIMIZATION/Library/MML_U2SA.for | `not_a_umat` |  |  |  |  |
| sy__UMAT_optimization_public/UMAT_U3_OPTIMIZATION/Library/MML_U3SA.FOR | `not_a_umat` |  |  |  |  |
| theysy__mml_subroutine_public/MML_U2/MML_U2.for | `unsupported_formulation` |  |  |  |  |
| theysy__mml_subroutine_public/MML_U3/MML_U3.FOR | `unsupported_formulation` |  |  |  |  |
| tmfrln__paraqus/examples/example_abaqus_extrusion_umat.f | `missing_material_data` |  |  |  |  |
| inaba__manforge/archives/fortran_fixed_form/yu_kinematic_3d_abaqus.for | `transform_refused` |  |  |  |  |
| uinaba__manforge/archives/fortran_fixed_form/yu_kinematic_3d_fixed.for | `transform_refused` |  |  |  |  |
| toruinaba__manforge/fortran/j2_isotropic_3d.f90 | `transform_refused` |  |  |  |  |
| toruinaba__manforge/fortran/yu_kinematic_3d.f90 | `transform_refused` |  |  |  |  |
| toruinaba__manforge/fortran/yu_kinematic_ps.f90 | `transform_refused` |  |  |  |  |
| _Sozio_Lopez-Pamies/Examples/C3D8H/UT kappa_mu=1/UMAT_KLP_RK5_hybrid.f | `original_job_failed` | C3D8H |  |  |  |
| vishalsubbiah__Abaqus-Multi-scale-modelling/Abaqus/umatcode3.f | `transform_refused` |  |  |  |  |
| /Legacy_Adapters_Reference/Adapters/Material/Adapters/UMAT_Adapter.f90 | `transform_refused` |  |  |  |  |
| per_Guide/Legacy_Adapters_Reference/Adapters/Material/UMAT_Adapter.f90 | `external_dependency_unavailable` |  |  |  |  |
| zning8251-jpg__ufc-fem-kernel/tests/TEST_PH_Mat_UMAT.f90 | `not_a_umat` |  |  |  |  |
| -jpg__ufc-fem-kernel/ufc_core/L6_AP/Input/Script/AP_InpScript_User.f90 | `not_a_umat` |  |  |  |  |
| zorkzou__UniMoVib/src/math.f90 | `not_a_umat` |  |  |  |  |
