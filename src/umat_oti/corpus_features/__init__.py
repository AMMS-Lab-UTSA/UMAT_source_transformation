"""Routine-level verification of corpus UMAT features (no Abaqus).

Gauss owns everything here except ``loading_paths.py`` and
``mechanics_checks.py`` (Curie). Entry points: :mod:`.harness`
(``resolve_entry``, ``run_entry``, ``evaluate_path``), :mod:`.fd` (FD ladder,
plateau rule D-4, nonsmooth classification), :mod:`.drivers` (Fortran
drivers), :mod:`.paths` (fallback loading paths and Abaqus kinematics).
"""
