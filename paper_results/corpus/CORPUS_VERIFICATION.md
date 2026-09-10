# Corpus verification

391 acquired artefacts, of which 338 present a UMAT interface to Abaqus.

**1 fully verified.**

`fully_verified` means the source transformed and compiled, Abaqus ran
the ORIGINAL, Abaqus ran the CONVERTED build on the same deck, their
stress and state histories agreed over the whole path, and the OTI
tangent agreed with a finite difference of the original at several
states along it. Compiling is not working and running is not verified.

## Finished, and unfinished

| | entries |
| --- | ---: |
| verified | 1 |
| blocked outside this repository | 86 |
| work remaining here | 304 |

## Every terminal state

| terminal state | whose move | entries |
| --- | --- | ---: |
| `not_attempted` | internal | 203 |
| `transform_refused` | internal | 91 |
| `not_a_umat` | external | 53 |
| `external_dependency_unavailable` | external | 24 |
| `missing_material_data` | external | 9 |
| `tangent_not_verified` | internal | 5 |
| `original_job_failed` | internal | 2 |
| `primal_disagreed` | internal | 2 |
| `fully_verified` | verified | 1 |
| `unsupported_formulation` | internal | 1 |

## What is left here, by cluster

Each of these is a limitation of this pipeline, not of the corpus. They are listed largest first because that is the order they are worth fixing in.

| cluster | entries |
| --- | ---: |
| `not_attempted` | 203 |
| `transform_refused` | 91 |
| `tangent_not_verified` | 5 |
| `original_job_failed` | 2 |
| `primal_disagreed` | 2 |
| `unsupported_formulation` | 1 |

## Every entry

| source | terminal state | element | primal | tangent | states |
| --- | --- | --- | ---: | ---: | --- |
| 3MAH__simcoon/testBin/Umats/UMABA/external/UMAT_ABAQUS_ELASTIC.f | `missing_material_data` |  |  |  |  |
| erical_geolab_materials/UMATERIALS/CAUCHY3D-DP/hyplast_Cauchy3D-DP.for | `missing_material_data` |  |  |  |  |
| AlexanderJFDR__Hyperelastic_phase_field/umat/NeoHookean_umat.for | `tangent_not_verified` | C3D8 | 4.90e-11 | 8.24e-04 | 2/4 |
| AnargyrosKarakalas__UMAT_3D/UMAT_3D_Coupled_ML_IP_Original.for | `transform_refused` |  |  |  |  |
| Mresearch__fenics-constitutive/examples/umat/src/umat_linear_elastic.f | `missing_material_data` |  |  |  |  |
| BBahtiri__ABAQUS-Multiphysics-Diffusion-UEL/Diffusion_3D.for | `external_dependency_unavailable` |  |  |  |  |
| araFEM-lite/src/programs/dev/xx15/francesc/umat_DP_primal_CPPM_def.f90 | `not_a_umat` |  |  |  |  |
| Batmanabcdefg__ParaFEM-lite/src/programs/dev/xx15/plasticity_xx15.F90 | `not_a_umat` |  |  |  |  |
| BristolCompositesInstitute__abaci/example/src/umat.f | `external_dependency_unavailable` |  |  |  |  |
| BristolCompositesInstitute__abaci/test/data/umat.f | `fully_verified` | C3D8 | 0.00e+00 | 8.51e-13 | 4/4 |
| BristolCompositesInstitute__abaqus-modern-fortran/src/umat.f | `external_dependency_unavailable` |  |  |  |  |
| E-UMAT-subroutine-for-3D-Composite-fatigue-simulation-Fortran-Code.for | `transform_refused` |  |  |  |  |
| -simulation/CAE_ASSISTANT_UMAT_Subroutine_ABAQUS_COMPOSITE_FATIGUE.for | `missing_material_data` |  |  |  |  |
| CAEAssistant-Group__Abaqus-UEL-Subroutine/Abaqus_UEL_Subroutine.f | `transform_refused` |  |  |  |  |
| alysis-of-composite-curing/Path_Dependent-Abaqus-Curing-Subroutine.for | `missing_material_data` |  |  |  |  |
| qus-Isotropic-Elasticity-Isothermal-Suboutine/ISOTROPIC-ELASTICITY.for | `original_job_failed` | C3D8 |  |  |  |
| Tsai-Hill-Orthotropic-Composite-Subroutine/PLANESTRESS-ORTHOTROPIC.for | `unsupported_formulation` | CPS4 |  |  |  |
| analysis-of-composite-curing/Abaqus-Viscoelastic-Curing-Subroutine.for | `transform_refused` |  |  |  |  |
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
| neral-shape-control-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Axe.for | `tangent_not_verified` | C3D8H | 0.00e+00 | 8.88e-03 | 0/2 |
| eral-shape-control-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Disk.for | `tangent_not_verified` | C3D8H | 0.00e+00 | 1.63e-03 | 0/2 |
| l-shape-control-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Scallop.for | `primal_disagreed` | C3D8H | 1.08e-07 |  |  |
| pe-control-of-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-DupinCyclide.for | `primal_disagreed` | C3D8H | 7.91e-08 |  |  |
| al-shape-control-of-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-Genhel.for | `tangent_not_verified` | C3D8H | 0.00e+00 | 8.13e-04 | 0/2 |
| al-shape-control-of-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-Saddle.for | `tangent_not_verified` | C3D8H | 0.00e+00 | 8.55e-03 | 0/2 |
| ral-shape-control-of-shell/Abaqus_Files/3Dto3D/From-3D-to-3D-Petal.for | `not_attempted` |  |  |  |  |
| -shape-control-of-shell/Abaqus_Files/3Dto3D/From-3D-to-3D-SeaShell.for | `not_attempted` |  |  |  |  |
| neral-shape-control-of-shell/Abaqus_Files/Alex_Shocked/Growth-Alex.for | `original_job_failed` | C3D8H |  |  |  |
| General-shape-control-of-shell/Abaqus_Files/Beetle_Taxi/Growth-Car.for | `not_attempted` |  |  |  |  |
| eneral-shape-control-of-shell/Abaqus_Files/FaceChange/Growth-Robot.for | `not_attempted` |  |  |  |  |
| orces/Examples-In-Section-3/ArcDown/Th001/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| -Under-Body-Forces/Examples-In-Section-3/ArcDown/Th001/PureGravity.for | `not_attempted` |  |  |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th001/PureGrowth.for | `not_attempted` |  |  |  |  |
| orces/Examples-In-Section-3/ArcDown/Th002/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| -Under-Body-Forces/Examples-In-Section-3/ArcDown/Th002/PureGravity.for | `not_attempted` |  |  |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th002/PureGrowth.for | `not_attempted` |  |  |  |  |
| -In-Section-3/ArcDown/Th005-Visualization/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| orces/Examples-In-Section-3/ArcDown/Th005/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th005/PureGrowth.for | `not_attempted` |  |  |  |  |
| Forces/Examples-In-Section-3/ArcDown/Th01/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th01/PureGravity.for | `not_attempted` |  |  |  |  |
| th-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th01/PureGrowth.for | `not_attempted` |  |  |  |  |
| -Forces/Examples-In-Section-3/ArcUp/Th001/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| wth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th001/PureGrowth.for | `not_attempted` |  |  |  |  |
| -Forces/Examples-In-Section-3/ArcUp/Th002/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| wth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th002/PureGrowth.for | `not_attempted` |  |  |  |  |
| es-In-Section-3/ArcUp/Th005-Visualization/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| -Forces/Examples-In-Section-3/ArcUp/Th005/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| wth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th005/PureGrowth.for | `not_attempted` |  |  |  |  |
| y-Forces/Examples-In-Section-3/ArcUp/Th01/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| wth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th01/PureGravity.for | `not_attempted` |  |  |  |  |
| owth-Under-Body-Forces/Examples-In-Section-3/ArcUp/Th01/PureGrowth.for | `not_attempted` |  |  |  |  |
| y-Forces/Examples-In-Section-3/Flat/Th001/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| owth-Under-Body-Forces/Examples-In-Section-3/Flat/Th001/PureGrowth.for | `not_attempted` |  |  |  |  |
| les-In-Section-3/Flat/Th002-Visualization/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| y-Forces/Examples-In-Section-3/Flat/Th002/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| owth-Under-Body-Forces/Examples-In-Section-3/Flat/Th002/PureGrowth.for | `not_attempted` |  |  |  |  |
| les-In-Section-3/Flat/Th005-Visualization/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| y-Forces/Examples-In-Section-3/Flat/Th005/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| wth-Under-Body-Forces/Examples-In-Section-3/Flat/Th005/PureGravity.for | `not_attempted` |  |  |  |  |
| owth-Under-Body-Forces/Examples-In-Section-3/Flat/Th005/PureGrowth.for | `not_attempted` |  |  |  |  |
| dy-Forces/Examples-In-Section-3/Flat/Th01/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| rowth-Under-Body-Forces/Examples-In-Section-3/Flat/Th01/PureGrowth.for | `not_attempted` |  |  |  |  |
| orces/Examples-In-Section-3/HelixUp/Th001/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| -Under-Body-Forces/Examples-In-Section-3/HelixUp/Th001/PureGravity.for | `not_attempted` |  |  |  |  |
| orces/Examples-In-Section-3/HelixUp/Th002/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| -Under-Body-Forces/Examples-In-Section-3/HelixUp/Th002/PureGravity.for | `not_attempted` |  |  |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/HelixUp/Th002/PureGrowth.for | `not_attempted` |  |  |  |  |
| orces/Examples-In-Section-3/HelixUp/Th005/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| -Under-Body-Forces/Examples-In-Section-3/HelixUp/Th005/PureGravity.for | `not_attempted` |  |  |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/HelixUp/Th005/PureGrowth.for | `not_attempted` |  |  |  |  |
| Forces/Examples-In-Section-3/HelixUp/Th01/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| h-Under-Body-Forces/Examples-In-Section-3/HelixUp/Th01/PureGravity.for | `not_attempted` |  |  |  |  |
| Examples-In-Section-3/ParabolicDown/Th001/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| -Body-Forces/Examples-In-Section-3/ParabolicDown/Th001/PureGravity.for | `not_attempted` |  |  |  |  |
| Examples-In-Section-3/ParabolicDown/Th002/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| r-Body-Forces/Examples-In-Section-3/ParabolicDown/Th002/PureGrowth.for | `not_attempted` |  |  |  |  |
| Examples-In-Section-3/ParabolicDown/Th005/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| -Body-Forces/Examples-In-Section-3/ParabolicDown/Th005/PureGravity.for | `not_attempted` |  |  |  |  |
| er-Body-Forces/Examples-In-Section-3/ParabolicDown/Th01/PureGrowth.for | `not_attempted` |  |  |  |  |
| der-Body-Forces/Examples-In-Section-3/ParabolicUp/Th001/PureGrowth.for | `not_attempted` |  |  |  |  |
| der-Body-Forces/Examples-In-Section-3/ParabolicUp/Th002/PureGrowth.for | `not_attempted` |  |  |  |  |
| es/Examples-In-Section-3/ParabolicUp/Th01/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| ples-In-Section-4/Experiment-DRAGONSKIN20-ArcDown/Th01/PureGravity.for | `not_attempted` |  |  |  |  |
| mples-In-Section-4/Experiment-DRAGONSKIN20-ArcDown/Th01/PureGrowth.for | `not_attempted` |  |  |  |  |
| xamples-In-Section-4/Experiment-DRAGONSKIN20-Flat/Th005/PureGrowth.for | `not_attempted` |  |  |  |  |
| Examples-In-Section-4/Experiment-DRAGONSKIN20-Flat/Th01/PureGrowth.for | `not_attempted` |  |  |  |  |
| ples-In-Section-4/Experiment-ECOFLEX0030-ArcDown/Th005/PureGravity.for | `not_attempted` |  |  |  |  |
| mples-In-Section-4/Experiment-ECOFLEX0030-ArcDown/Th01/PureGravity.for | `not_attempted` |  |  |  |  |
| ction-4/Experiment-ECOFLEX0030-Flat/Th005/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| Examples-In-Section-4/Experiment-ECOFLEX0030-Flat/Th005/PureGrowth.for | `not_attempted` |  |  |  |  |
| ection-4/Experiment-ECOFLEX0030-Flat/Th01/BodyForce-Growth-2Stages.for | `not_attempted` |  |  |  |  |
| dy-Forces/PathSensitivity/Th001-1MPa/BodyForce-Growth-GravityFirst.for | `not_attempted` |  |  |  |  |
| dy-Forces/PathSensitivity/Th001-5MPa/BodyForce-Growth-Simultaneous.for | `not_attempted` |  |  |  |  |
| rface-conformal-mappings/Analytical_Example/2D/inputFile/Growth-EX.for | `not_attempted` |  |  |  |  |
| rface-conformal-mappings/Analytical_Example/2D/inputFile/Growth-Z2.for | `not_attempted` |  |  |  |  |
| ace-conformal-mappings/Analytical_Example/2D/inputFile/Growth-frac.for | `not_attempted` |  |  |  |  |
| -conformal-mappings/Analytical_Example/3D/InputFile/Growth-MinSur1.for | `not_attempted` |  |  |  |  |
| -conformal-mappings/Analytical_Example/3D/InputFile/Growth-MinSur2.for | `not_attempted` |  |  |  |  |
| -conformal-mappings/Analytical_Example/3D/InputFile/Growth-MinSur3.for | `not_attempted` |  |  |  |  |
| mal-mappings/Analytical_Example/3D/MMAFile/Example1/Growth-MinSur1.for | `not_attempted` |  |  |  |  |
| mal-mappings/Analytical_Example/3D/MMAFile/Example2/Growth-MinSur2.for | `not_attempted` |  |  |  |  |
| pings/Analytical_Example/3D/MMAFile/Example3-Sphere/Growth-MinSur3.for | `not_attempted` |  |  |  |  |
| ppings/Analytical_Example/3D/MMAFile/Example4-Torus/Growth-MinSur3.for | `not_attempted` |  |  |  |  |
| ace-conformal-mappings/Bunny/Part1/ABAQUS_files/Growth-Bunny-Part1.for | `not_attempted` |  |  |  |  |
| ace-conformal-mappings/Bunny/Part2/ABAQUS_files/Growth-Bunny-Part2.for | `not_attempted` |  |  |  |  |
| face-conformal-mappings/Hunman_face/ABAQUS_files/Growth-Human-face.for | `not_attempted` |  |  |  |  |
| -and-surface-conformal-mappings/Instability_Analysis/Growth-Sphere.for | `not_attempted` |  |  |  |  |
| urface-conformal-mappings/Mesh_Convergence_test/2D/EX/10/Growth-EX.for | `not_attempted` |  |  |  |  |
| ce-conformal-mappings/Mesh_Convergence_test/2D/Frac/10/Growth-Frac.for | `not_attempted` |  |  |  |  |
| urface-conformal-mappings/Mesh_Convergence_test/2D/Z2/10/Growth-Z2.for | `not_attempted` |  |  |  |  |
| rmal-mappings/Mesh_Convergence_test/3D/Catenoid/10/Growth-Catenoid.for | `not_attempted` |  |  |  |  |
| rmal-mappings/Mesh_Convergence_test/3D/Helicoid/10/Growth-Helicoid.for | `not_attempted` |  |  |  |  |
| onformal-mappings/Mesh_Convergence_test/3D/Sphere/10/Growth-Sphere.for | `not_attempted` |  |  |  |  |
| ce-conformal-mappings/Mesh_Convergence_test/Alex/20470/Growth-Alex.for | `not_attempted` |  |  |  |  |
| face-conformal-mappings/Mesh_Convergence_test/Alex/749/Growth-Alex.for | `not_attempted` |  |  |  |  |
| surface-conformal-mappings/Model_car/ABAQUS_files/Growth-Model-car.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE1.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE2.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE3.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE1.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE2.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE3.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE1.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE2.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE3.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE4.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE5.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/ShapeProgramming/Growth-CASE6.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-101.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-102.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-103.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-11.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-12.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-13.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-shell/Input files and UMAT/Example1/SweetMelon.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-shell/Input files and UMAT/Example2/MorningGlory.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-shell/Input files and UMAT/Example3/Trachea.for | `not_attempted` |  |  |  |  |
| Jeff97__growth-of-shell/Input files and UMAT/Example4/Apple.for | `not_attempted` |  |  |  |  |
| owth-of-shell/Input files and UMAT/Example5/CereusForbesiiSpiralis.for | `not_attempted` |  |  |  |  |
| 97__growth-of-shell/Input files and UMAT/Example6/TendrilOfPumpkin.for | `not_attempted` |  |  |  |  |
| JuliaFEM__UMAT.jl/umat_models/drucker_prager_plasticity.f90 | `transform_refused` |  |  |  |  |
| JuliaFEM__UMAT.jl/umat_models/gurson_porous_plasticity.f90 | `transform_refused` |  |  |  |  |
| KianAbd__vCANN_FEM/Abaqus/umat.f90 | `transform_refused` |  |  |  |  |
| KianAbd__vCANN_FEM/Abaqus/umat_vCANN.f90 | `not_attempted` |  |  |  |  |
| KianAbd__vCANN_FEM/Abaqus/umat_vCANN.for | `not_attempted` |  |  |  |  |
| FEM/TensorFlow/Results_Liao_Thermo/20260601-103627/UMAT/umat_vCANN.for | `not_attempted` |  |  |  |  |
| KnutAM__MaterialModels/models/CrystalPlasticity/src/taylor_model.f90 | `transform_refused` |  |  |  |  |
| tAM__MaterialModels/models/GenFiniteStrain/src/GeneralFiniteStrain.for | `external_dependency_unavailable` |  |  |  |  |
| nutAM__MaterialModels/models/GenSmallStrain/src/GeneralSmallStrain.f90 | `transform_refused` |  |  |  |  |
| KnutAM__MaterialModels/models/MM2021/src/umat.f90 | `transform_refused` |  |  |  |  |
| KnutAM__MaterialModels/models/Qin2018/src/umat.f90 | `transform_refused` |  |  |  |  |
| LallyLabTCD__localBasisAbaqus/Case studies/umat_MA_global.for | `transform_refused` |  |  |  |  |
| LallyLabTCD__localBasisAbaqus/Case studies/umat_MA_local.for | `transform_refused` |  |  |  |  |
| esson C - fibre reinforced anistropic models/Abaqus/umat_MA_global.for | `transform_refused` |  |  |  |  |
| Lesson C - fibre reinforced anistropic models/Abaqus/umat_MA_local.for | `transform_refused` |  |  |  |  |
| MCM-QMUL__PhaseFieldComp/Subroutine/UELUMATPhaseField_AT2.for | `not_attempted` |  |  |  |  |
| PeriDoX__PeriDoX/Publications/2022_JOSS/data/UMAT/base.f | `not_attempted` |  |  |  |  |
| PeriHub__PeriLab.jl/src/Models/Material/UMATs/base.f | `not_attempted` |  |  |  |  |
| PeriHub__PeriLab.jl/src/Models/Material/UMATs/usertest.f | `transform_refused` |  |  |  |  |
| titutiveModels/fortran_models/linear_elastic/UMAT_LinearElasticity.f90 | `not_attempted` |  |  |  |  |
| tes__ConstitutiveModels/fortran_models/mohr_coulomb/UMAT_MohrCoulomb.f | `not_attempted` |  |  |  |  |
| RafalMichalczyk__PavementDesign/Subroutines/umat_gmaxwell.for | `not_attempted` |  |  |  |  |
| RafalMichalczyk__PavementDesign/Subroutines/umat_ms_plast.for | `not_attempted` |  |  |  |  |
| ReachOptimum__mlpcp-interp-dic/abaqus/UMMDp_FLC.f | `transform_refused` |  |  |  |  |
| RickAlb__UMAT-DFD-Lebedev/all_subroutines/UMAT_DFD_LEB.for | `transform_refused` |  |  |  |  |
| RitioL__PolyFatigueCrackSim/CPFEM-val/subroutines_revised.for | `not_attempted` |  |  |  |  |
| RitioL__PolyFatigueCrackSim/workplace/huang_umat_97.for | `not_attempted` |  |  |  |  |
| RitioL__PolyFatigueCrackSim/workplace/subroutines3_revised.for | `not_attempted` |  |  |  |  |
| __DIC2ABAQUS/OXFORD-UMAT/Example - Polycrytal with PROPS/OXFORD-UMAT.f | `transform_refused` |  |  |  |  |
| n__DIC2ABAQUS/OXFORD-UMAT/Example - Residual deformation/OXFORD-UMAT.f | `transform_refused` |  |  |  |  |
| Shi2oon__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v2.26/OXFORD-UMAT.f | `transform_refused` |  |  |  |  |
| Shi2oon__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v3.1/OXFORD-UMAT.f | `transform_refused` |  |  |  |  |
| Shi2oon__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v3.3/OXFORD-UMAT.f | `transform_refused` |  |  |  |  |
| Sina-Taghizadeh__UMAT_Hyperelastic/CompresibleNeoHookean.for | `not_attempted` |  |  |  |  |
| Woowinehouse__ABQ-UMAT-Sanisand-High/src/interface/umat.f90 | `external_dependency_unavailable` |  |  |  |  |
| Woowinehouse__Abaqus_UMAT_sanisand/merge/source.F90 | `not_attempted` |  |  |  |  |
| Woowinehouse__Abaqus_UMAT_sanisand/src/interface/umat.f90 | `external_dependency_unavailable` |  |  |  |  |
| orlthen__20220314-abqus-simulation/abaqus/enhanced/enhanced_curing.for | `not_attempted` |  |  |  |  |
| __20220314-abqus-simulation/abaqus/original/array_with_two_pixel_z.for | `not_attempted` |  |  |  |  |
| hen__20220314-abqus-simulation/abaqus/simplified/simplified_curing.for | `not_attempted` |  |  |  |  |
| Yutu0k__ABQflow/examples/07_SubroutineJob/subroutine/umat_elastic.for | `not_attempted` |  |  |  |  |
| abuganza__BayesianCalibrationSkinGrowth/GOH_Example.f | `not_attempted` |  |  |  |  |
| abuganza__BayesianCalibrationSkinGrowth/Iso_Example.f | `not_attempted` |  |  |  |  |
| librationSkinGrowth/Revision/Abaqus SImulation/GOH/BC1_50cc/GOH_50cc.f | `not_attempted` |  |  |  |  |
| librationSkinGrowth/Revision/Abaqus SImulation/GOH/BC1_55cc/GOH_55cc.f | `not_attempted` |  |  |  |  |
| ionSkinGrowth/Revision/Abaqus SImulation/Isotropic/BC1_50cc/Iso_50cc.f | `not_attempted` |  |  |  |  |
| ionSkinGrowth/Revision/Abaqus SImulation/Isotropic/BC1_60cc/Iso_60cc.f | `not_attempted` |  |  |  |  |
| ionSkinGrowth/Revision/Abaqus SImulation/Isotropic/BC2_60cc/Iso_60cc.f | `not_attempted` |  |  |  |  |
| onSkinGrowth/Revision/Abaqus SImulation/SampleSimulation/GOH_Example.f | `not_attempted` |  |  |  |  |
| onSkinGrowth/Revision/Abaqus SImulation/SampleSimulation/Iso_Example.f | `not_attempted` |  |  |  |  |
| abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_strain.f | `not_attempted` |  |  |  |  |
| abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_stress.f | `not_attempted` |  |  |  |  |
| abuganza__UMAT_anisotropic_damage/UMAT_Tissue_3d.f | `not_attempted` |  |  |  |  |
| adtzlr__ttb/docs/examples/Abaqus/umat_nh_ttb.f | `transform_refused` |  |  |  |  |
| adtzlr__ttb/docs/examples/Abaqus/umat_nh_ttb_simple.f | `transform_refused` |  |  |  |  |
| adtzlr__ttb/docs/examples/script_umat.f | `not_a_umat` |  |  |  |  |
| ahartloper__UVC_MatMod/Abaqus/UVCmultiaxial.for | `transform_refused` |  |  |  |  |
| ahartloper__UVC_MatMod/Abaqus/UVCplanestress.for | `not_attempted` |  |  |  |  |
| ahartloper__UVC_MatMod/Abaqus/UVCuniaxial.for | `transform_refused` |  |  |  |  |
| ahartloper__UVC_MatMod/Abaqus/UVCuniaxial_IS.for | `transform_refused` |  |  |  |  |
| artorg-unibe-ch__HFE/02_CODE/abq/UMAT_BIPHASIC.f | `not_attempted` |  |  |  |  |
| ge-UMAT-Public/HETVAL_nonLocalLemaitre/HETVAL_lemaitreDamageNonLocal.f | `not_attempted` |  |  |  |  |
| _Lemaitre-damage-UMAT-Public/nonLocalLemaitre/lemaitreDamageNonLocal.f | `not_attempted` |  |  |  |  |
| MechanicalFoam/abaqusUMATs/abaqusUmatMohrCoulomb/MohrCoulombAbaqus.for | `transform_refused` |  |  |  |  |
| bennifuchs__TsaiWu-Fortran/abaqus-umat-interface.f90 | `transform_refused` |  |  |  |  |
| bennifuchs__TsaiWu-Fortran/umat.f90 | `transform_refused` |  |  |  |  |
| m_simulate/abaqus/scriptbase/benchmark_abaqus_scripts/veni_mix_model.f | `transform_refused` |  |  |  |  |
| imulate/abaqus/scriptbase/benchmark_abaqus_scripts/vevp_leonov_model.f | `not_attempted` |  |  |  |  |
| _simulate/abaqus/scriptbase/benchmark_abaqus_scripts/vp_leonov_model.f | `not_attempted` |  |  |  |  |
| bmmbUPF__abaqusIVD/Sub_MechDisc.f | `transform_refused` |  |  |  |  |
| bmmbUPF__abaqusIVD/Sub_TransDisc.f | `transform_refused` |  |  |  |  |
| brizzer__elmerfem_piezo/fem/src/modules/ElasticSolve.F90 | `not_a_umat` |  |  |  |  |
| calculix__ccx_fff/src/umat.f | `not_attempted` |  |  |  |  |
| compas-dev__compas_fea2/data/umat/umat-hooke-iso.f | `not_attempted` |  |  |  |  |
| compas-dev__compas_fea2/data/umat/umat-hooke-transversaliso.f | `not_attempted` |  |  |  |  |
| core-marine-dev__elmerfem/fem/src/modules/ElasticSolve.F90 | `not_a_umat` |  |  |  |  |
| cunhuav__Abaqus-Neural-Network-UMAT/ro_nn_umat.f90 | `transform_refused` |  |  |  |  |
| damin225__short-crack-propagation-3d/input_clean/umat.f | `transform_refused` |  |  |  |  |
| davidmorinNTNU__ABAQUS_subroutines/V_UMAT/UMAT.f | `transform_refused` |  |  |  |  |
| ekurth__NEML/util/abaqus/nemlumat.f | `external_dependency_unavailable` |  |  |  |  |
| frodal__SCMM-hypo/HypoImp.f | `external_dependency_unavailable` |  |  |  |  |
| glu46__3D_anisotropic_viscoelastic_model/OrthoWoodCreep_Column.for | `not_attempted` |  |  |  |  |
| glu46__3D_anisotropic_viscoelastic_model/OrthoWoodCreep_General.for | `not_attempted` |  |  |  |  |
| glu46__3D_anisotropic_viscoelastic_model/Ortho_WoodCreep_Cube.for | `not_attempted` |  |  |  |  |
| glu46__3D_anisotropic_viscoelastic_model/TIRockCreep_CANEY.for | `not_attempted` |  |  |  |  |
| glu46__3D_anisotropic_viscoelastic_model/TIRockCreep_GENERAL.for | `not_attempted` |  |  |  |  |
| hamza-djeloud__thesis_project/plate_with_notch.for | `not_attempted` |  |  |  |  |
| harshaa765__Bilinear-CZM-UMAT/Bilinear_CZM_UMAT.for | `not_attempted` |  |  |  |  |
| harshaa765__UMATFile/UMAT.for | `transform_refused` |  |  |  |  |
| hwu12sluedu__MaterialAI-Workbench/examples/UMAT/ml_umat.f | `transform_refused` |  |  |  |  |
| u__MaterialAI-Workbench/material_ai_workbench/resources/umat/ml_umat.f | `transform_refused` |  |  |  |  |
| ibf-RWTH__GA-Calibration/subroutine/Umat_CP.for | `transform_refused` |  |  |  |  |
| irfancn__Abaqus-UEL-elastic/uel_elastic.for | `not_attempted` |  |  |  |  |
| irfancn__Abaqus-UMAT-elastic/umat_elastic.for | `not_attempted` |  |  |  |  |
| irfancn__Abaqus-UMAT-viscoelastic/umat_viscoelastic.for | `not_attempted` |  |  |  |  |
| j-machacek__numgeo-hardening-soil-bricks/src/hs-bricks-umat/umat.f90 | `external_dependency_unavailable` |  |  |  |  |
| umgeo-hardening-soil-bricks/src/incremental-driver/material_models.f90 | `external_dependency_unavailable` |  |  |  |  |
| j-machacek__numgeo-hypo-igs-isa-gis/src/material_models.f90 | `external_dependency_unavailable` |  |  |  |  |
| jacojvr__UMATs/UMAT_framework/umat_comb.f | `transform_refused` |  |  |  |  |
| jacojvr__UMATs/UMAT_framework/umat_iso.f | `transform_refused` |  |  |  |  |
| baqus_subroutine_skills/official_examples/umat/umat_elastic_official.f | `not_attempted` |  |  |  |  |
| routine_skills/official_examples/umat/umat_mises_plasticity_official.f | `not_attempted` |  |  |  |  |
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
| keisuke58__pde-fem-biofilm/umat_biofilm_visco_2ch.f | `not_attempted` |  |  |  |  |
| keisuke58__pde-fem-biofilm/umat_biofilm_visco_phase2.f | `not_attempted` |  |  |  |  |
| learnitmyway__Paperboard/Fortran/umat.f90 | `not_a_umat` |  |  |  |  |
| llnl__ExaConstit/src/umats/umat.f | `transform_refused` |  |  |  |  |
| aqus6.14-5-UMAT-constative-model/Duncan-Chang_EB_UMAT_ABAQUS6.14-5.for | `transform_refused` |  |  |  |  |
| it__thesis-benchmark-cases/Benchmarks/Fuel_pellet_quarter/czmHealing.f | `not_attempted` |  |  |  |  |
| it__thesis-benchmark-cases/Benchmarks/Notched_plate_shear/czmHealing.f | `not_attempted` |  |  |  |  |
| luisez1988__Viscoplastic-NorSand/UMAT_Nor_Sand_Zamb.for | `transform_refused` |  |  |  |  |
| luisez1988__Viscoplastic-SSMC/UMAT_SSMCWStrainRates_Zambrano.for | `not_a_umat` |  |  |  |  |
| luisez1988__Viscoplastic_MC_coupled/UMAT_MCWStrainRates_Zambrano.for | `not_a_umat` |  |  |  |  |
| makkemal__NGIMASEM/usermat.F | `not_a_umat` |  |  |  |  |
| marioruiarruda__Hashin_2D_UMAT/umat_hashin_f90.f90 | `transform_refused` |  |  |  |  |
| marioruiarruda__Hashin_3D_UMAT/umat_hashin3D_f90.f90 | `transform_refused` |  |  |  |  |
| marioruiarruda__Mazars_UMAT/umat_mazars_f90.f90 | `transform_refused` |  |  |  |  |
| marioruiarruda__Tsai-Wu_2D_UMAT/umat_tsaiwu_f90.f90 | `transform_refused` |  |  |  |  |
| matmodlab__matmodlab2/matmodlab2/umat/uhyper_wrap.f90 | `transform_refused` |  |  |  |  |
| matmodlab__matmodlab2/matmodlab2/umat/umats/umat_neohooke.f90 | `not_attempted` |  |  |  |  |
| matmodlab__matmodlab2/matmodlab2/umat/umats/umat_stub.f90 | `transform_refused` |  |  |  |  |
| matmodlab__matmodlab2/matmodlab2/umat/umats/umat_thermoelastic.f90 | `not_attempted` |  |  |  |  |
| mauroarcidiacono__Crystal-Plasticity-UMAT/umat_abaqus.for | `external_dependency_unavailable` |  |  |  |  |
| mauroarcidiacono__Crystal-Plasticity-UMAT/umat_standalone.for | `external_dependency_unavailable` |  |  |  |  |
| olla__BMMB24/simulations/input files/umat_transverseIsotropicStretch.f | `not_attempted` |  |  |  |  |
| mholla__SOFT24/simulations/UMAT_axon_tension.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_area_morph.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_area_morph_Abaqus.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_area_morph_orient.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_area_stretch.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_fiber_morph.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_fiber_morph_Abaqus.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_fiber_morph_orient.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_fiber_stretch.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_iso_Mandel.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_iso_Mandel_v2.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_iso_morph.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_iso_morph_Abaqus.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_iso_stretch.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_neohooke.f | `not_attempted` |  |  |  |  |
| mholla__growth/umats/umat_neohooke_abaqus.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_ortho_stretch.f | `transform_refused` |  |  |  |  |
| mholla__growth/umats/umat_transverse.f | `not_attempted` |  |  |  |  |
| n Code_Basic_Viscoelasticity/ABAQUS_DSR_EXAMPLE/ViscoelasticityCode3.f | `transform_refused` |  |  |  |  |
| scoelastictiy/Fortran Code_Basic_Viscoelasticity/ViscoelasticityCode.f | `not_a_umat` |  |  |  |  |
| coelastictiy/Fortran Code_Basic_Viscoelasticity/ViscoelasticityCode2.f | `not_a_umat` |  |  |  |  |
| coelastictiy/Fortran Code_Basic_Viscoelasticity/ViscoelasticityCode3.f | `not_a_umat` |  |  |  |  |
| tictiy/Linking Mechanical with Aging Code/CoupledMechanicalAgingCode.f | `not_a_umat` |  |  |  |  |
| ictiy/Linking Mechanical with Aging Code/CoupledMechanicalAgingCode2.f | `not_a_umat` |  |  |  |  |
| mrkearden__abaqus_umat/ElasticSolve.F90 | `external_dependency_unavailable` |  |  |  |  |
| mrkearden__abaqus_umat/PlasticSolve.F90 | `not_a_umat` |  |  |  |  |
| mrkearden__abaqus_umat/UMAT.F90 | `external_dependency_unavailable` |  |  |  |  |
| grilli__Oxford_Crystal_Plasticity/ExampleInputFiles/HCPnoTwin/umat.for | `external_dependency_unavailable` |  |  |  |  |
| nsundar__PFM_UMAT_ElastoPlastic/UMAT_phasefield_plasticity.f | `not_attempted` |  |  |  |  |
| aubach__abaqus-explicit/examples/_pile_driving/HPP_Staubach_explicit.f | `transform_refused` |  |  |  |  |
| patrickstaubach__abaqus-explicit/src/HPP_Staubach_explicit.f | `transform_refused` |  |  |  |  |
| peer-open-source__xara/SRC/domain/peri/umat.for | `external_dependency_unavailable` |  |  |  |  |
| phhannequart__UMAT_sma_hannequart/UMAT_sma_hannequart.for | `not_attempted` |  |  |  |  |
| stic/src/abaqusUMATs/abaqusUmatLinearElastic/abaqusUmatLinearElastic.f | `transform_refused` |  |  |  |  |
| la__ferrite-fortran-integration_using_Julia/src/Material_Models/umat.f | `transform_refused` |  |  |  |  |
| rhdodds__warp3d/src/user_routines_umat.f | `not_a_umat` |  |  |  |  |
| MAT - Strain-based Return Mapping - Fully-Implicit/umat_subroutine.for | `not_a_umat` |  |  |  |  |
| UMAT - Strain-based Return Mapping - Semi-Implicit/umat_subroutine.for | `not_a_umat` |  |  |  |  |
| MAT - Stress-based Return Mapping - Fully-Implicit/umat_subroutine.for | `not_a_umat` |  |  |  |  |
| UMAT - Stress-based Return Mapping - Semi-Implicit/umat_subroutine.for | `not_a_umat` |  |  |  |  |
| i__Tahoe/development/src/elements/solid/materials/ABAQUS_BCJ/bcj_iso.f | `transform_refused` |  |  |  |  |
| sas229__geomat/src/umat/src/umat.f90 | `external_dependency_unavailable` |  |  |  |  |
| sas229__geomat/tests/umat_integration.f90 | `external_dependency_unavailable` |  |  |  |  |
| sd104400__OPA_Modeling/FE Modeling/UMAT_DPIsodwAniDM.for | `transform_refused` |  |  |  |  |
| seekzzh__mat-model-lab/assets/templates/abaqus_umat.f | `not_attempted` |  |  |  |  |
| shayansss__bioumat/SUBROUTINES.FOR | `not_attempted` |  |  |  |  |
| shayansss__hml/NONLIPLS.for | `not_attempted` |  |  |  |  |
| simoneponcioni__HFE/02_CODE/abq/UMAT_BIPHASIC.f | `not_attempted` |  |  |  |  |
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
| thealanjason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_1EL.for | `not_attempted` |  |  |  |  |
| thealanjason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_2EL.for | `not_attempted` |  |  |  |  |
| thealanjason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_3EL.for | `not_attempted` |  |  |  |  |
| njason__umat_finite_viscoelasticity/report/chapters/VISC_OGDEN_2EL.for | `not_attempted` |  |  |  |  |
| _umat_finite_viscoelasticity/simulation_input_files/VISC_OGDEN_1EL.for | `not_attempted` |  |  |  |  |
| _umat_finite_viscoelasticity/simulation_input_files/VISC_OGDEN_2EL.for | `not_attempted` |  |  |  |  |
| _umat_finite_viscoelasticity/simulation_input_files/VISC_OGDEN_3EL.for | `not_attempted` |  |  |  |  |
| thelfer__tfel/mtest/tests/mtest/castem/umat.f | `transform_refused` |  |  |  |  |
| sy__UMAT_optimization_public/UMAT_U2_OPTIMIZATION/Library/MML_U2SA.for | `not_a_umat` |  |  |  |  |
| sy__UMAT_optimization_public/UMAT_U3_OPTIMIZATION/Library/MML_U3SA.FOR | `not_a_umat` |  |  |  |  |
| theysy__mml_subroutine_public/MML_U2/MML_U2.for | `not_attempted` |  |  |  |  |
| theysy__mml_subroutine_public/MML_U3/MML_U3.FOR | `not_attempted` |  |  |  |  |
| tmfrln__paraqus/examples/example_abaqus_extrusion_umat.f | `not_attempted` |  |  |  |  |
| inaba__manforge/archives/fortran_fixed_form/yu_kinematic_3d_abaqus.for | `transform_refused` |  |  |  |  |
| uinaba__manforge/archives/fortran_fixed_form/yu_kinematic_3d_fixed.for | `transform_refused` |  |  |  |  |
| toruinaba__manforge/fortran/j2_isotropic_3d.f90 | `transform_refused` |  |  |  |  |
| toruinaba__manforge/fortran/yu_kinematic_3d.f90 | `transform_refused` |  |  |  |  |
| toruinaba__manforge/fortran/yu_kinematic_ps.f90 | `transform_refused` |  |  |  |  |
| _Sozio_Lopez-Pamies/Examples/C3D8H/UT kappa_mu=1/UMAT_KLP_RK5_hybrid.f | `not_attempted` |  |  |  |  |
| vishalsubbiah__Abaqus-Multi-scale-modelling/Abaqus/umatcode3.f | `transform_refused` |  |  |  |  |
| /Legacy_Adapters_Reference/Adapters/Material/Adapters/UMAT_Adapter.f90 | `transform_refused` |  |  |  |  |
| per_Guide/Legacy_Adapters_Reference/Adapters/Material/UMAT_Adapter.f90 | `external_dependency_unavailable` |  |  |  |  |
| zning8251-jpg__ufc-fem-kernel/tests/TEST_PH_Mat_UMAT.f90 | `not_a_umat` |  |  |  |  |
| -jpg__ufc-fem-kernel/ufc_core/L6_AP/Input/Script/AP_InpScript_User.f90 | `not_a_umat` |  |  |  |  |
| zorkzou__UniMoVib/src/math.f90 | `not_a_umat` |  |  |  |  |
