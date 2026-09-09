# Corpus verification report

391 acquired entries, of which 332 present a UMAT interface to Abaqus.

**67 fully verified** (20.2% of the UMATs).

Only `fully_verified` counts. It means the source transformed and
compiled, Abaqus ran the ORIGINAL, Abaqus ran the CONVERTED build
on the same deck, their stress and state histories agreed over the
whole path, and the OTI tangent agreed with a finite difference of
the original at several states along it. Compiling is not working,
and running is not verified.

## Where every entry stands

| status | entries |
| --- | --- |
| `acquired` | 111 |
| `metadata_resolved` | 4 |
| `transformed` | 42 |
| `compiled` | 17 |
| `abaqus_original_passed` | 7 |
| `abaqus_transformed_passed` | 44 |
| `primal_parity_passed` | 40 |
| `fully_verified` | 67 |
| `not_a_umat` | 59 |

## Every UMAT entry

| source                                                     | status                     | iface |    primal |   tangent | states |
|------------------------------------------------------------|----------------------------|-------|-----------|-----------|--------|
| simcoon/testBin/Umats/UMABA/external/UMAT_ABAQUS_ELASTIC.f | transformed                | -     |         - |         - |      - |
| b_materials/UMATERIALS/CAUCHY3D-DP/hyplast_Cauchy3D-DP.for | transformed                | -     |         - |         - |      - |
| derJFDR__Hyperelastic_phase_field/umat/NeoHookean_umat.for | primal_parity_passed       | -     |  0.00e+00 |  2.90e-07 |    2/3 |
| gyrosKarakalas__UMAT_3D/UMAT_3D_Coupled_ML_IP_Original.for | acquired                   | UMAT  |         - |         - |      - |
| enics-constitutive/examples/umat/src/umat_linear_elastic.f | transformed                | -     |         - |         - |      - |
| ahtiri__ABAQUS-Multiphysics-Diffusion-UEL/Diffusion_3D.for | acquired                   | UMAT  |         - |         - |      - |
| BristolCompositesInstitute__abaci/example/src/umat.f       | acquired                   | UMAT  |         - |         - |      - |
| BristolCompositesInstitute__abaci/test/data/umat.f         | fully_verified             | -     |  0.00e+00 |  1.77e-13 |    3/3 |
| istolCompositesInstitute__abaqus-modern-fortran/src/umat.f | acquired                   | UMAT  |         - |         - |      - |
| utine-for-3D-Composite-fatigue-simulation-Fortran-Code.for | acquired                   | UMAT  |         - |         - |      - |
| CAE_ASSISTANT_UMAT_Subroutine_ABAQUS_COMPOSITE_FATIGUE.for | transformed                | -     |         - |         - |      - |
| stant-Group__Abaqus-UEL-Subroutine/Abaqus_UEL_Subroutine.f | acquired                   | UMAT  |         - |         - |      - |
| mposite-curing/Path_Dependent-Abaqus-Curing-Subroutine.for | transformed                | -     |         - |         - |      - |
| c-Elasticity-Isothermal-Suboutine/ISOTROPIC-ELASTICITY.for | fully_verified             | -     |  0.00e+00 |  4.62e-13 |    3/3 |
| thotropic-Composite-Subroutine/PLANESTRESS-ORTHOTROPIC.for | metadata_resolved          | -     |         - |         - |      - |
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
| _Gradient_Enhanced_Damage_UMAT/src/UMAT_DamThermMech_1_H.f | acquired                   | UMAT  |         - |         - |      - |
| control-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Axe.for | primal_parity_passed       | -     |  0.00e+00 |  1.12e-03 |    1/3 |
| ontrol-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Disk.for | primal_parity_passed       | -     |  0.00e+00 |  2.47e-04 |    1/3 |
| rol-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Scallop.for | abaqus_transformed_passed  | -     |  1.97e-08 |         - |      - |
| f-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-DupinCyclide.for | abaqus_transformed_passed  | -     |  6.41e-08 |         - |      - |
| trol-of-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-Genhel.for | primal_parity_passed       | -     |  0.00e+00 |  5.43e-05 |    1/3 |
| trol-of-shell/Abaqus_Files/2Dto3D/From-2D-to-3D-Saddle.for | primal_parity_passed       | -     |  0.00e+00 |  4.45e-04 |    1/3 |
| ntrol-of-shell/Abaqus_Files/3Dto3D/From-3D-to-3D-Petal.for | abaqus_transformed_passed  | -     |  3.30e-09 |         - |      - |
| ol-of-shell/Abaqus_Files/3Dto3D/From-3D-to-3D-SeaShell.for | abaqus_transformed_passed  | -     |  1.56e-06 |         - |      - |
| control-of-shell/Abaqus_Files/Alex_Shocked/Growth-Alex.for | compiled                   | -     |         - |         - |      - |
| e-control-of-shell/Abaqus_Files/Beetle_Taxi/Growth-Car.for | compiled                   | -     |         - |         - |      - |
| -control-of-shell/Abaqus_Files/FaceChange/Growth-Robot.for | compiled                   | -     |         - |         - |      - |
| es-In-Section-3/ArcDown/Th001/BodyForce-Growth-2Stages.for | fully_verified             | -     |  1.34e-11 |  9.25e-07 |    3/3 |
| Forces/Examples-In-Section-3/ArcDown/Th001/PureGravity.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| -Forces/Examples-In-Section-3/ArcDown/Th001/PureGrowth.for | fully_verified             | -     |  1.36e-11 |  1.81e-07 |    3/3 |
| es-In-Section-3/ArcDown/Th002/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  1.35e-11 |  1.15e-06 |    2/3 |
| Forces/Examples-In-Section-3/ArcDown/Th002/PureGravity.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| -Forces/Examples-In-Section-3/ArcDown/Th002/PureGrowth.for | fully_verified             | -     |  1.36e-11 |  1.81e-07 |    3/3 |
| 3/ArcDown/Th005-Visualization/BodyForce-Growth-2Stages.for | fully_verified             | -     |  1.77e-11 |  1.06e-07 |    3/3 |
| es-In-Section-3/ArcDown/Th005/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  1.35e-11 |  2.74e-06 |    1/3 |
| -Forces/Examples-In-Section-3/ArcDown/Th005/PureGrowth.for | fully_verified             | -     |  1.36e-11 |  1.81e-07 |    3/3 |
| les-In-Section-3/ArcDown/Th01/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  1.35e-11 |  8.91e-07 |    2/3 |
| -Forces/Examples-In-Section-3/ArcDown/Th01/PureGravity.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| y-Forces/Examples-In-Section-3/ArcDown/Th01/PureGrowth.for | fully_verified             | -     |  1.36e-11 |  1.81e-07 |    3/3 |
| ples-In-Section-3/ArcUp/Th001/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  1.00e-07 |    2/3 |
| dy-Forces/Examples-In-Section-3/ArcUp/Th001/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  8.52e-08 |    3/3 |
| ples-In-Section-3/ArcUp/Th002/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  3.68e-07 |    2/3 |
| dy-Forces/Examples-In-Section-3/ArcUp/Th002/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  8.52e-08 |    3/3 |
| n-3/ArcUp/Th005-Visualization/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  8.72e-08 |    2/3 |
| ples-In-Section-3/ArcUp/Th005/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  6.50e-08 |    2/3 |
| dy-Forces/Examples-In-Section-3/ArcUp/Th005/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  8.52e-08 |    3/3 |
| mples-In-Section-3/ArcUp/Th01/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  8.50e-08 |    3/3 |
| dy-Forces/Examples-In-Section-3/ArcUp/Th01/PureGravity.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| ody-Forces/Examples-In-Section-3/ArcUp/Th01/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  8.52e-08 |    3/3 |
| mples-In-Section-3/Flat/Th001/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  2.13e-07 |    3/3 |
| ody-Forces/Examples-In-Section-3/Flat/Th001/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| on-3/Flat/Th002-Visualization/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  8.12e-08 |    2/3 |
| mples-In-Section-3/Flat/Th002/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  0.00e+00 |  8.12e-08 |    2/3 |
| ody-Forces/Examples-In-Section-3/Flat/Th002/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| on-3/Flat/Th005-Visualization/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  1.54e-07 |    3/3 |
| mples-In-Section-3/Flat/Th005/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  1.54e-07 |    3/3 |
| dy-Forces/Examples-In-Section-3/Flat/Th005/PureGravity.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| ody-Forces/Examples-In-Section-3/Flat/Th005/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| amples-In-Section-3/Flat/Th01/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  9.71e-08 |    3/3 |
| Body-Forces/Examples-In-Section-3/Flat/Th01/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| es-In-Section-3/HelixUp/Th001/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  2.30e-07 |    3/3 |
| Forces/Examples-In-Section-3/HelixUp/Th001/PureGravity.for | fully_verified             | -     |  0.00e+00 |  2.30e-07 |    3/3 |
| es-In-Section-3/HelixUp/Th002/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  2.30e-07 |    3/3 |
| Forces/Examples-In-Section-3/HelixUp/Th002/PureGravity.for | fully_verified             | -     |  0.00e+00 |  2.30e-07 |    3/3 |
| -Forces/Examples-In-Section-3/HelixUp/Th002/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  2.30e-07 |    3/3 |
| es-In-Section-3/HelixUp/Th005/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  2.30e-07 |    3/3 |
| Forces/Examples-In-Section-3/HelixUp/Th005/PureGravity.for | fully_verified             | -     |  0.00e+00 |  2.30e-07 |    3/3 |
| -Forces/Examples-In-Section-3/HelixUp/Th005/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  2.30e-07 |    3/3 |
| les-In-Section-3/HelixUp/Th01/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  2.30e-07 |    3/3 |
| -Forces/Examples-In-Section-3/HelixUp/Th01/PureGravity.for | fully_verified             | -     |  0.00e+00 |  2.30e-07 |    3/3 |
| Section-3/ParabolicDown/Th001/BodyForce-Growth-2Stages.for | fully_verified             | -     |  1.61e-12 |  3.63e-07 |    3/3 |
| /Examples-In-Section-3/ParabolicDown/Th001/PureGravity.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| Section-3/ParabolicDown/Th002/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  1.61e-12 |  3.00e-07 |    2/3 |
| s/Examples-In-Section-3/ParabolicDown/Th002/PureGrowth.for | fully_verified             | -     |  1.68e-12 |  4.08e-08 |    3/3 |
| Section-3/ParabolicDown/Th005/BodyForce-Growth-2Stages.for | primal_parity_passed       | -     |  1.65e-12 |  2.66e-07 |    2/3 |
| /Examples-In-Section-3/ParabolicDown/Th005/PureGravity.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| es/Examples-In-Section-3/ParabolicDown/Th01/PureGrowth.for | fully_verified             | -     |  1.68e-12 |  4.08e-08 |    3/3 |
| ces/Examples-In-Section-3/ParabolicUp/Th001/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  6.34e-08 |    3/3 |
| ces/Examples-In-Section-3/ParabolicUp/Th002/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  6.34e-08 |    3/3 |
| In-Section-3/ParabolicUp/Th01/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  3.83e-07 |    3/3 |
| ion-4/Experiment-DRAGONSKIN20-ArcDown/Th01/PureGravity.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| tion-4/Experiment-DRAGONSKIN20-ArcDown/Th01/PureGrowth.for | abaqus_transformed_passed  | -     |  8.90e-08 |         - |      - |
| ection-4/Experiment-DRAGONSKIN20-Flat/Th005/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  9.42e-08 |    3/3 |
| Section-4/Experiment-DRAGONSKIN20-Flat/Th01/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  1.22e-07 |    3/3 |
| ion-4/Experiment-ECOFLEX0030-ArcDown/Th005/PureGravity.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| tion-4/Experiment-ECOFLEX0030-ArcDown/Th01/PureGravity.for | fully_verified             | -     |  0.00e+00 |  3.40e-08 |    3/3 |
| riment-ECOFLEX0030-Flat/Th005/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  3.66e-08 |    3/3 |
| Section-4/Experiment-ECOFLEX0030-Flat/Th005/PureGrowth.for | fully_verified             | -     |  0.00e+00 |  3.34e-08 |    3/3 |
| eriment-ECOFLEX0030-Flat/Th01/BodyForce-Growth-2Stages.for | fully_verified             | -     |  0.00e+00 |  5.39e-07 |    3/3 |
| thSensitivity/Th001-1MPa/BodyForce-Growth-GravityFirst.for | primal_parity_passed       | -     |  1.50e-12 |  1.00e-07 |    2/3 |
| thSensitivity/Th001-5MPa/BodyForce-Growth-Simultaneous.for | primal_parity_passed       | -     |  1.00e-12 |  1.17e-07 |    2/3 |
| mal-mappings/Analytical_Example/2D/inputFile/Growth-EX.for | abaqus_transformed_passed  | -     |  7.34e-07 |         - |      - |
| mal-mappings/Analytical_Example/2D/inputFile/Growth-Z2.for | abaqus_transformed_passed  | -     |  7.23e-08 |         - |      - |
| l-mappings/Analytical_Example/2D/inputFile/Growth-frac.for | abaqus_transformed_passed  | -     |  2.12e-08 |         - |      - |
| appings/Analytical_Example/3D/InputFile/Growth-MinSur1.for | primal_parity_passed       | -     |  0.00e+00 |  4.37e-03 |    2/3 |
| appings/Analytical_Example/3D/InputFile/Growth-MinSur2.for | primal_parity_passed       | -     |  0.00e+00 |  1.44e-04 |    1/3 |
| appings/Analytical_Example/3D/InputFile/Growth-MinSur3.for | fully_verified             | -     |  0.00e+00 |  2.24e-08 |    3/3 |
| /Analytical_Example/3D/MMAFile/Example1/Growth-MinSur1.for | primal_parity_passed       | -     |  0.00e+00 |  5.86e-03 |    0/3 |
| /Analytical_Example/3D/MMAFile/Example2/Growth-MinSur2.for | primal_parity_passed       | -     |  0.00e+00 |  9.90e-07 |    1/3 |
| ical_Example/3D/MMAFile/Example3-Sphere/Growth-MinSur3.for | fully_verified             | -     |  0.00e+00 |  2.75e-08 |    3/3 |
| tical_Example/3D/MMAFile/Example4-Torus/Growth-MinSur3.for | fully_verified             | -     |  0.00e+00 |  2.75e-08 |    3/3 |
| l-mappings/Bunny/Part1/ABAQUS_files/Growth-Bunny-Part1.for | compiled                   | -     |         - |         - |      - |
| l-mappings/Bunny/Part2/ABAQUS_files/Growth-Bunny-Part2.for | compiled                   | -     |         - |         - |      - |
| al-mappings/Hunman_face/ABAQUS_files/Growth-Human-face.for | compiled                   | -     |         - |         - |      - |
| -conformal-mappings/Instability_Analysis/Growth-Sphere.for | fully_verified             | -     |  0.00e+00 |  2.24e-08 |    3/3 |
| rmal-mappings/Mesh_Convergence_test/2D/EX/10/Growth-EX.for | abaqus_transformed_passed  | -     |  2.39e-08 |         - |      - |
| -mappings/Mesh_Convergence_test/2D/Frac/10/Growth-Frac.for | abaqus_transformed_passed  | -     |  2.12e-08 |         - |      - |
| rmal-mappings/Mesh_Convergence_test/2D/Z2/10/Growth-Z2.for | abaqus_transformed_passed  | -     |  7.23e-08 |         - |      - |
| s/Mesh_Convergence_test/3D/Catenoid/10/Growth-Catenoid.for | primal_parity_passed       | -     |  0.00e+00 |  1.44e-04 |    1/3 |
| s/Mesh_Convergence_test/3D/Helicoid/10/Growth-Helicoid.for | primal_parity_passed       | -     |  0.00e+00 |  4.37e-03 |    2/3 |
| pings/Mesh_Convergence_test/3D/Sphere/10/Growth-Sphere.for | fully_verified             | -     |  0.00e+00 |  2.24e-08 |    3/3 |
| -mappings/Mesh_Convergence_test/Alex/20470/Growth-Alex.for | compiled                   | -     |         - |         - |      - |
| al-mappings/Mesh_Convergence_test/Alex/749/Growth-Alex.for | compiled                   | -     |         - |         - |      - |
| ormal-mappings/Model_car/ABAQUS_files/Growth-Model-car.for | compiled                   | -     |         - |         - |      - |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE1.for  | fully_verified             | -     |  0.00e+00 |  8.80e-09 |    3/3 |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE2.for  | abaqus_transformed_passed  | -     |  1.05e-06 |         - |      - |
| Jeff97__growth-of-circular-plate/Bending/Growth-CASE3.for  | abaqus_transformed_passed  | -     |  1.32e-07 |         - |      - |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE1.for | abaqus_transformed_passed  | -     |  8.13e-06 |         - |      - |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE2.for | abaqus_transformed_passed  | -     |  2.67e-07 |         - |      - |
| Jeff97__growth-of-circular-plate/Combined/Growth-CASE3.for | abaqus_transformed_passed  | -     |  2.29e-06 |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE1.for | abaqus_transformed_passed  | -     |  4.42e-08 |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE2.for | abaqus_transformed_passed  | -     |  1.51e-06 |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE3.for | abaqus_transformed_passed  | -     |  7.39e-08 |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE4.for | abaqus_transformed_passed  | -     |  2.64e-07 |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE5.for | abaqus_transformed_passed  | -     |  2.76e-03 |         - |      - |
| growth-of-circular-plate/ShapeProgramming/Growth-CASE6.for | abaqus_transformed_passed  | -     |  3.42e-08 |         - |      - |
| 7__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-101.for | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| 7__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-102.for | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| 7__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-103.for | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| 97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-11.for | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| 97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-12.for | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| 97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-13.for | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| owth-of-shell/Input files and UMAT/Example1/SweetMelon.for | abaqus_transformed_passed  | -     |  6.17e-06 |         - |      - |
| th-of-shell/Input files and UMAT/Example2/MorningGlory.for | abaqus_transformed_passed  | -     |  2.52e-06 |         - |      - |
| _growth-of-shell/Input files and UMAT/Example3/Trachea.for | abaqus_transformed_passed  | -     |  4.73e-07 |         - |      - |
| 7__growth-of-shell/Input files and UMAT/Example4/Apple.for | abaqus_transformed_passed  | -     |  6.37e-07 |         - |      - |
| l/Input files and UMAT/Example5/CereusForbesiiSpiralis.for | abaqus_transformed_passed  | -     |  5.81e-06 |         - |      - |
| f-shell/Input files and UMAT/Example6/TendrilOfPumpkin.for | compiled                   | -     |         - |         - |      - |
| uliaFEM__UMAT.jl/umat_models/drucker_prager_plasticity.f90 | acquired                   | UMAT  |         - |         - |      - |
| JuliaFEM__UMAT.jl/umat_models/gurson_porous_plasticity.f90 | acquired                   | UMAT  |         - |         - |      - |
| KianAbd__vCANN_FEM/Abaqus/umat.f90                         | acquired                   | UMAT  |         - |         - |      - |
| KianAbd__vCANN_FEM/Abaqus/umat_vCANN.f90                   | transformed                | -     |         - |         - |      - |
| KianAbd__vCANN_FEM/Abaqus/umat_vCANN.for                   | transformed                | -     |         - |         - |      - |
| ow/Results_Liao_Thermo/20260601-103627/UMAT/umat_vCANN.for | transformed                | -     |         - |         - |      - |
| terialModels/models/CrystalPlasticity/src/taylor_model.f90 | acquired                   | UMAT  |         - |         - |      - |
| lModels/models/GenFiniteStrain/src/GeneralFiniteStrain.for | acquired                   | UMAT  |         - |         - |      - |
| ialModels/models/GenSmallStrain/src/GeneralSmallStrain.f90 | acquired                   | UMAT  |         - |         - |      - |
| KnutAM__MaterialModels/models/MM2021/src/umat.f90          | acquired                   | UMAT  |         - |         - |      - |
| KnutAM__MaterialModels/models/Qin2018/src/umat.f90         | acquired                   | UMAT  |         - |         - |      - |
| lyLabTCD__localBasisAbaqus/Case studies/umat_MA_global.for | acquired                   | UMAT  |         - |         - |      - |
| llyLabTCD__localBasisAbaqus/Case studies/umat_MA_local.for | acquired                   | UMAT  |         - |         - |      - |
| bre reinforced anistropic models/Abaqus/umat_MA_global.for | acquired                   | UMAT  |         - |         - |      - |
| ibre reinforced anistropic models/Abaqus/umat_MA_local.for | acquired                   | UMAT  |         - |         - |      - |
| -QMUL__PhaseFieldComp/Subroutine/UELUMATPhaseField_AT2.for | abaqus_original_passed     | -     |         - |         - |      - |
| PeriDoX__PeriDoX/Publications/2022_JOSS/data/UMAT/base.f   | transformed                | -     |         - |         - |      - |
| PeriHub__PeriLab.jl/src/Models/Material/UMATs/base.f       | transformed                | -     |         - |         - |      - |
| PeriHub__PeriLab.jl/src/Models/Material/UMATs/usertest.f   | acquired                   | UMAT  |         - |         - |      - |
| ls/fortran_models/linear_elastic/UMAT_LinearElasticity.f90 | transformed                | -     |         - |         - |      - |
| utiveModels/fortran_models/mohr_coulomb/UMAT_MohrCoulomb.f | transformed                | -     |         - |         - |      - |
| ReachOptimum__mlpcp-interp-dic/abaqus/UMMDp_FLC.f          | acquired                   | UMAT  |         - |         - |      - |
| RickAlb__UMAT-DFD-Lebedev/all_subroutines/UMAT_DFD_LEB.for | acquired                   | UMAT  |         - |         - |      - |
| ioL__PolyFatigueCrackSim/CPFEM-val/subroutines_revised.for | fully_verified             | -     |  0.00e+00 |  2.15e-09 |    3/3 |
| RitioL__PolyFatigueCrackSim/workplace/huang_umat_97.for    | fully_verified             | -     |  0.00e+00 |  3.09e-09 |    3/3 |
| oL__PolyFatigueCrackSim/workplace/subroutines3_revised.for | fully_verified             | -     |  0.00e+00 |  2.15e-09 |    3/3 |
| /OXFORD-UMAT/Example - Polycrytal with PROPS/OXFORD-UMAT.f | acquired                   | UMAT  |         - |         - |      - |
| S/OXFORD-UMAT/Example - Residual deformation/OXFORD-UMAT.f | acquired                   | UMAT  |         - |         - |      - |
| on__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v2.26/OXFORD-UMAT.f | acquired                   | UMAT  |         - |         - |      - |
| oon__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v3.1/OXFORD-UMAT.f | acquired                   | UMAT  |         - |         - |      - |
| oon__DIC2ABAQUS/OXFORD-UMAT/OXFORD-UMAT v3.3/OXFORD-UMAT.f | acquired                   | UMAT  |         - |         - |      - |
| na-Taghizadeh__UMAT_Hyperelastic/CompresibleNeoHookean.for | fully_verified             | -     |  0.00e+00 |  5.24e-07 |    3/3 |
| oowinehouse__ABQ-UMAT-Sanisand-High/src/interface/umat.f90 | acquired                   | UMAT  |         - |         - |      - |
| Woowinehouse__Abaqus_UMAT_sanisand/merge/source.F90        | transformed                | -     |         - |         - |      - |
| Woowinehouse__Abaqus_UMAT_sanisand/src/interface/umat.f90  | acquired                   | UMAT  |         - |         - |      - |
| 20314-abqus-simulation/abaqus/enhanced/enhanced_curing.for | abaqus_original_passed     | -     |         - |         - |      - |
| bqus-simulation/abaqus/original/array_with_two_pixel_z.for | compiled                   | -     |         - |         - |      - |
| 4-abqus-simulation/abaqus/simplified/simplified_curing.for | abaqus_transformed_passed  | -     |       inf |         - |      - |
| flow/examples/07_SubroutineJob/subroutine/umat_elastic.for | transformed                | -     |         - |         - |      - |
| abuganza__BayesianCalibrationSkinGrowth/GOH_Example.f      | abaqus_original_passed     | -     |         - |         - |      - |
| abuganza__BayesianCalibrationSkinGrowth/Iso_Example.f      | primal_parity_passed       | -     |  0.00e+00 |  2.73e-08 |    2/3 |
| nGrowth/Revision/Abaqus SImulation/GOH/BC1_50cc/GOH_50cc.f | abaqus_original_passed     | -     |         - |         - |      - |
| nGrowth/Revision/Abaqus SImulation/GOH/BC1_55cc/GOH_55cc.f | abaqus_original_passed     | -     |         - |         - |      - |
| h/Revision/Abaqus SImulation/Isotropic/BC1_50cc/Iso_50cc.f | primal_parity_passed       | -     |  0.00e+00 |  2.73e-08 |    2/3 |
| h/Revision/Abaqus SImulation/Isotropic/BC1_60cc/Iso_60cc.f | primal_parity_passed       | -     |  0.00e+00 |  2.73e-08 |    2/3 |
| h/Revision/Abaqus SImulation/Isotropic/BC2_60cc/Iso_60cc.f | primal_parity_passed       | -     |  0.00e+00 |  2.73e-08 |    2/3 |
| /Revision/Abaqus SImulation/SampleSimulation/GOH_Example.f | abaqus_original_passed     | -     |         - |         - |      - |
| /Revision/Abaqus SImulation/SampleSimulation/Iso_Example.f | primal_parity_passed       | -     |  0.00e+00 |  2.73e-08 |    2/3 |
| nza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_strain.f | primal_parity_passed       | -     |  0.00e+00 |         - |    0/3 |
| nza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_stress.f | primal_parity_passed       | -     |  0.00e+00 |         - |    0/3 |
| abuganza__UMAT_anisotropic_damage/UMAT_Tissue_3d.f         | abaqus_transformed_passed  | -     |  1.14e-05 |         - |      - |
| adtzlr__ttb/docs/examples/Abaqus/umat_nh_ttb.f             | acquired                   | UMAT  |         - |         - |      - |
| adtzlr__ttb/docs/examples/Abaqus/umat_nh_ttb_simple.f      | acquired                   | UMAT  |         - |         - |      - |
| ahartloper__UVC_MatMod/Abaqus/UVCmultiaxial.for            | acquired                   | UMAT  |         - |         - |      - |
| ahartloper__UVC_MatMod/Abaqus/UVCplanestress.for           | compiled                   | -     |         - |         - |      - |
| ahartloper__UVC_MatMod/Abaqus/UVCuniaxial.for              | acquired                   | UMAT  |         - |         - |      - |
| ahartloper__UVC_MatMod/Abaqus/UVCuniaxial_IS.for           | acquired                   | UMAT  |         - |         - |      - |
| artorg-unibe-ch__HFE/02_CODE/abq/UMAT_BIPHASIC.f           | transformed                | -     |         - |         - |      - |
| ic/HETVAL_nonLocalLemaitre/HETVAL_lemaitreDamageNonLocal.f | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| mage-UMAT-Public/nonLocalLemaitre/lemaitreDamageNonLocal.f | fully_verified             | -     |  0.00e+00 |  5.01e-13 |    3/3 |
| am/abaqusUMATs/abaqusUmatMohrCoulomb/MohrCoulombAbaqus.for | acquired                   | UMAT  |         - |         - |      - |
| bennifuchs__TsaiWu-Fortran/abaqus-umat-interface.f90       | acquired                   | UMAT  |         - |         - |      - |
| bennifuchs__TsaiWu-Fortran/umat.f90                        | acquired                   | UMAT  |         - |         - |      - |
| baqus/scriptbase/benchmark_abaqus_scripts/veni_mix_model.f | acquired                   | UMAT  |         - |         - |      - |
| us/scriptbase/benchmark_abaqus_scripts/vevp_leonov_model.f | transformed                | -     |         - |         - |      - |
| aqus/scriptbase/benchmark_abaqus_scripts/vp_leonov_model.f | transformed                | -     |         - |         - |      - |
| bmmbUPF__abaqusIVD/Sub_MechDisc.f                          | acquired                   | UMAT  |         - |         - |      - |
| bmmbUPF__abaqusIVD/Sub_TransDisc.f                         | acquired                   | UMAT  |         - |         - |      - |
| calculix__ccx_fff/src/umat.f                               | transformed                | -     |         - |         - |      - |
| compas-dev__compas_fea2/data/umat/umat-hooke-iso.f         | transformed                | -     |         - |         - |      - |
| pas-dev__compas_fea2/data/umat/umat-hooke-transversaliso.f | transformed                | -     |         - |         - |      - |
| cunhuav__Abaqus-Neural-Network-UMAT/ro_nn_umat.f90         | acquired                   | UMAT  |         - |         - |      - |
| davidmorinNTNU__ABAQUS_subroutines/V_UMAT/UMAT.f           | acquired                   | UMAT  |         - |         - |      - |
| ekurth__NEML/util/abaqus/nemlumat.f                        | acquired                   | UMAT  |         - |         - |      - |
| frodal__SCMM-hypo/HypoImp.f                                | acquired                   | UMAT  |         - |         - |      - |
| D_anisotropic_viscoelastic_model/OrthoWoodCreep_Column.for | transformed                | -     |         - |         - |      - |
| _anisotropic_viscoelastic_model/OrthoWoodCreep_General.for | transformed                | -     |         - |         - |      - |
| 3D_anisotropic_viscoelastic_model/Ortho_WoodCreep_Cube.for | transformed                | -     |         - |         - |      - |
| 6__3D_anisotropic_viscoelastic_model/TIRockCreep_CANEY.for | transformed                | -     |         - |         - |      - |
| _3D_anisotropic_viscoelastic_model/TIRockCreep_GENERAL.for | transformed                | -     |         - |         - |      - |
| hamza-djeloud__thesis_project/plate_with_notch.for         | primal_parity_passed       | -     |  0.00e+00 |         - |    0/3 |
| harshaa765__Bilinear-CZM-UMAT/Bilinear_CZM_UMAT.for        | metadata_resolved          | -     |         - |         - |      - |
| harshaa765__UMATFile/UMAT.for                              | acquired                   | UMAT  |         - |         - |      - |
| hwu12sluedu__MaterialAI-Workbench/examples/UMAT/ml_umat.f  | acquired                   | UMAT  |         - |         - |      - |
| I-Workbench/material_ai_workbench/resources/umat/ml_umat.f | acquired                   | UMAT  |         - |         - |      - |
| ibf-RWTH__GA-Calibration/subroutine/Umat_CP.for            | acquired                   | UMAT  |         - |         - |      - |
| irfancn__Abaqus-UEL-elastic/uel_elastic.for                | fully_verified             | -     |  0.00e+00 |  4.76e-13 |    3/3 |
| irfancn__Abaqus-UMAT-elastic/umat_elastic.for              | fully_verified             | -     |  0.00e+00 |  7.76e-13 |    3/3 |
| irfancn__Abaqus-UMAT-viscoelastic/umat_viscoelastic.for    | abaqus_transformed_passed  | -     |  2.29e-04 |         - |      - |
| __numgeo-hardening-soil-bricks/src/hs-bricks-umat/umat.f90 | acquired                   | UMAT  |         - |         - |      - |
| ing-soil-bricks/src/incremental-driver/material_models.f90 | acquired                   | UMAT  |         - |         - |      - |
| -machacek__numgeo-hypo-igs-isa-gis/src/material_models.f90 | acquired                   | UMAT  |         - |         - |      - |
| jacojvr__UMATs/UMAT_framework/umat_comb.f                  | acquired                   | UMAT  |         - |         - |      - |
| jacojvr__UMATs/UMAT_framework/umat_iso.f                   | acquired                   | UMAT  |         - |         - |      - |
| tine_skills/official_examples/umat/umat_elastic_official.f | transformed                | -     |         - |         - |      - |
| ls/official_examples/umat/umat_mises_plasticity_official.f | transformed                | -     |         - |         - |      - |
| urry__pipelining/elmerfem/fem/src/modules/ElasticSolve.F90 | acquired                   | UMAT  |         - |         - |      - |
| jpsferreira__UMAT-ABAQUS/src/_umat.for                     | acquired                   | UMAT  |         - |         - |      - |
| jpsferreira__UMAT-ABAQUS/test_in_abaqus/umat_general.for   | acquired                   | UMAT  |         - |         - |      - |
| jpsferreira__UMAT-ABAQUS/umat_general.for                  | acquired                   | UMAT  |         - |         - |      - |
| keisuke58__pde-fem-biofilm/umat_biofilm_visco.f            | acquired                   | UMAT  |         - |         - |      - |
| keisuke58__pde-fem-biofilm/umat_biofilm_visco_2ch.f        | transformed                | -     |         - |         - |      - |
| keisuke58__pde-fem-biofilm/umat_biofilm_visco_phase2.f     | primal_parity_passed       | -     |  0.00e+00 |  3.24e-02 |    0/3 |
| llnl__ExaConstit/src/umats/umat.f                          | acquired                   | UMAT  |         - |         - |      - |
| MAT-constative-model/Duncan-Chang_EB_UMAT_ABAQUS6.14-5.for | acquired                   | UMAT  |         - |         - |      - |
| enchmark-cases/Benchmarks/Fuel_pellet_quarter/czmHealing.f | abaqus_transformed_passed  | -     |  1.00e+00 |         - |      - |
| enchmark-cases/Benchmarks/Notched_plate_shear/czmHealing.f | abaqus_transformed_passed  | -     |  1.00e+00 |         - |      - |
| marioruiarruda__Hashin_2D_UMAT/umat_hashin_f90.f90         | acquired                   | UMAT  |         - |         - |      - |
| marioruiarruda__Hashin_3D_UMAT/umat_hashin3D_f90.f90       | acquired                   | UMAT  |         - |         - |      - |
| marioruiarruda__Mazars_UMAT/umat_mazars_f90.f90            | acquired                   | UMAT  |         - |         - |      - |
| marioruiarruda__Tsai-Wu_2D_UMAT/umat_tsaiwu_f90.f90        | acquired                   | UMAT  |         - |         - |      - |
| matmodlab__matmodlab2/matmodlab2/umat/uhyper_wrap.f90      | acquired                   | UMAT  |         - |         - |      - |
| modlab__matmodlab2/matmodlab2/umat/umats/umat_neohooke.f90 | transformed                | -     |         - |         - |      - |
| matmodlab__matmodlab2/matmodlab2/umat/umats/umat_stub.f90  | acquired                   | UMAT  |         - |         - |      - |
| b__matmodlab2/matmodlab2/umat/umats/umat_thermoelastic.f90 | transformed                | -     |         - |         - |      - |
| mauroarcidiacono__Crystal-Plasticity-UMAT/umat_abaqus.for  | acquired                   | UMAT  |         - |         - |      - |
| roarcidiacono__Crystal-Plasticity-UMAT/umat_standalone.for | acquired                   | UMAT  |         - |         - |      - |
| /simulations/input files/umat_transverseIsotropicStretch.f | primal_parity_passed       | -     |  0.00e+00 |  2.13e-05 |    1/3 |
| mholla__SOFT24/simulations/UMAT_axon_tension.f             | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_area_morph.f                     | fully_verified             | -     |  0.00e+00 |  2.74e-07 |    3/3 |
| mholla__growth/umats/umat_area_morph_Abaqus.f              | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| mholla__growth/umats/umat_area_morph_orient.f              | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_area_stretch.f                   | primal_parity_passed       | -     |  0.00e+00 |  5.22e-08 |    2/3 |
| mholla__growth/umats/umat_fiber_morph.f                    | fully_verified             | -     |  0.00e+00 |  8.48e-08 |    3/3 |
| mholla__growth/umats/umat_fiber_morph_Abaqus.f             | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| mholla__growth/umats/umat_fiber_morph_orient.f             | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_fiber_stretch.f                  | primal_parity_passed       | -     |  0.00e+00 |  5.22e-08 |    2/3 |
| mholla__growth/umats/umat_iso_Mandel.f                     | primal_parity_passed       | -     |  0.00e+00 |  5.22e-08 |    2/3 |
| mholla__growth/umats/umat_iso_Mandel_v2.f                  | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_iso_morph.f                      | primal_parity_passed       | -     |  0.00e+00 |  2.61e-08 |    2/3 |
| mholla__growth/umats/umat_iso_morph_Abaqus.f               | abaqus_transformed_passed  | -     |  0.00e+00 |         - |      - |
| mholla__growth/umats/umat_iso_stretch.f                    | primal_parity_passed       | -     |  0.00e+00 |  5.22e-08 |    2/3 |
| mholla__growth/umats/umat_neohooke.f                       | compiled                   | -     |         - |         - |      - |
| mholla__growth/umats/umat_neohooke_abaqus.f                | acquired                   | UMAT  |         - |         - |      - |
| mholla__growth/umats/umat_ortho_stretch.f                  | abaqus_original_passed     | -     |         - |         - |      - |
| mholla__growth/umats/umat_transverse.f                     | primal_parity_passed       | -     |  0.00e+00 |  5.22e-08 |    2/3 |
| _Viscoelasticity/ABAQUS_DSR_EXAMPLE/ViscoelasticityCode3.f | acquired                   | UMAT  |         - |         - |      - |
| mrkearden__abaqus_umat/ElasticSolve.F90                    | acquired                   | UMAT  |         - |         - |      - |
| mrkearden__abaqus_umat/UMAT.F90                            | acquired                   | UMAT  |         - |         - |      - |
| rd_Crystal_Plasticity/ExampleInputFiles/HCPnoTwin/umat.for | acquired                   | UMAT  |         - |         - |      - |
| us-explicit/examples/_pile_driving/HPP_Staubach_explicit.f | acquired                   | UMAT  |         - |         - |      - |
| trickstaubach__abaqus-explicit/src/HPP_Staubach_explicit.f | acquired                   | UMAT  |         - |         - |      - |
| peer-open-source__xara/SRC/domain/peri/umat.for            | acquired                   | UMAT  |         - |         - |      - |
| phhannequart__UMAT_sma_hannequart/UMAT_sma_hannequart.for  | transformed                | -     |         - |         - |      - |
| qusUMATs/abaqusUmatLinearElastic/abaqusUmatLinearElastic.f | acquired                   | UMAT  |         - |         - |      - |
| fortran-integration_using_Julia/src/Material_Models/umat.f | acquired                   | UMAT  |         - |         - |      - |
| elopment/src/elements/solid/materials/ABAQUS_BCJ/bcj_iso.f | acquired                   | UMAT  |         - |         - |      - |
| sas229__geomat/src/umat/src/umat.f90                       | acquired                   | UMAT  |         - |         - |      - |
| sas229__geomat/tests/umat_integration.f90                  | acquired                   | UMAT  |         - |         - |      - |
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
| jason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_1EL.for | abaqus_transformed_passed  | -     |       inf |         - |      - |
| jason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_2EL.for | abaqus_transformed_passed  | -     |       inf |         - |      - |
| jason__umat_finite_viscoelasticity/UMAT/VISC_OGDEN_3EL.for | transformed                | -     |         - |         - |      - |
| _finite_viscoelasticity/report/chapters/VISC_OGDEN_2EL.for | compiled                   | -     |         - |         - |      - |
| _viscoelasticity/simulation_input_files/VISC_OGDEN_1EL.for | compiled                   | -     |         - |         - |      - |
| _viscoelasticity/simulation_input_files/VISC_OGDEN_2EL.for | compiled                   | -     |         - |         - |      - |
| _viscoelasticity/simulation_input_files/VISC_OGDEN_3EL.for | transformed                | -     |         - |         - |      - |
| thelfer__tfel/mtest/tests/mtest/castem/umat.f              | acquired                   | UMAT  |         - |         - |      - |
| theysy__mml_subroutine_public/MML_U2/MML_U2.for            | metadata_resolved          | -     |         - |         - |      - |
| theysy__mml_subroutine_public/MML_U3/MML_U3.FOR            | metadata_resolved          | -     |         - |         - |      - |
| tmfrln__paraqus/examples/example_abaqus_extrusion_umat.f   | transformed                | -     |         - |         - |      - |
| rge/archives/fortran_fixed_form/yu_kinematic_3d_abaqus.for | acquired                   | UMAT  |         - |         - |      - |
| orge/archives/fortran_fixed_form/yu_kinematic_3d_fixed.for | acquired                   | UMAT  |         - |         - |      - |
| toruinaba__manforge/fortran/j2_isotropic_3d.f90            | acquired                   | UMAT  |         - |         - |      - |
| toruinaba__manforge/fortran/yu_kinematic_3d.f90            | acquired                   | UMAT  |         - |         - |      - |
| toruinaba__manforge/fortran/yu_kinematic_ps.f90            | acquired                   | UMAT  |         - |         - |      - |
| -Pamies/Examples/C3D8H/UT kappa_mu=1/UMAT_KLP_RK5_hybrid.f | compiled                   | -     |         - |         - |      - |
| alsubbiah__Abaqus-Multi-scale-modelling/Abaqus/umatcode3.f | acquired                   | UMAT  |         - |         - |      - |
| ters_Reference/Adapters/Material/Adapters/UMAT_Adapter.f90 | acquired                   | UMAT  |         - |         - |      - |
| gacy_Adapters_Reference/Adapters/Material/UMAT_Adapter.f90 | acquired                   | UMAT  |         - |         - |      - |
