"""Acceptance tests for the higher-order OTI Fortran generator (Priority 3).

Verifies:

* mixed-direction enumeration (E12, E112, E122, E1122, ...) is exercised,
* repeated-direction enumeration (E11, E111, E1111, E22, ..., E2222) is
  exercised,
* factorial recovery factors are applied correctly
  (``recovered_derivative = raw_coefficient * prod_of_factorials``),
* deterministic ordering is preserved (the directions CSV is byte-stable
  and matches the canonical enumeration),
* the emitted Fortran is compilable with a modern gfortran and runs to
  completion,
* every recovered derivative agrees with SymPy analytical differentiation
  through order 4 to <= 1e-10 in this scaled polynomial model.

Tests are skipped when gfortran is absent (environmental blocker).
"""

from __future__ import annotations

import csv
import shutil
from math import factorial
from pathlib import Path

import pytest
import sympy as sp

from umat_oti.fortran_emit.higher_order_strain import (
    HigherOrderModel,
    analytical_derivatives,
    compile_higher_order_build,
    generate_higher_order_build,
    read_derivatives_csv,
    run_higher_order_driver,
)
from umat_oti.oti.oti_directions import imaginary_directions, member_name


REQUIRES_GFORTRAN = pytest.mark.skipif(
    shutil.which("gfortran") is None,
    reason="gfortran not on PATH (environmental blocker).",
)


# ---------------------------------------------------------------------------
# Direction enumeration (pure-Python, no compile required)
# ---------------------------------------------------------------------------

def test_direction_enumeration_covers_mixed_and_repeated():
    dirs = imaginary_directions(nbases=2, order=4)
    names = [d["name"] for d in dirs]
    # Order 1: two singletons
    assert names[:2] == ["E1", "E2"]
    # Order 2: E11 (repeated), E12 (mixed), E22 (repeated) -- deterministic.
    assert names[2:5] == ["E11", "E12", "E22"]
    # Order 3 and 4 -- verify each expected multiset appears exactly once.
    order3 = [d["bases"] for d in dirs if d["order"] == 3]
    assert sorted(order3) == [(1, 1, 1), (1, 1, 2), (1, 2, 2), (2, 2, 2)]
    order4 = [d["bases"] for d in dirs if d["order"] == 4]
    assert sorted(order4) == [
        (1, 1, 1, 1),
        (1, 1, 1, 2),
        (1, 1, 2, 2),
        (1, 2, 2, 2),
        (2, 2, 2, 2),
    ]


def test_factorial_recovery_factors_match_multiplicities():
    """recovery_factor = product of factorials of the multiplicities."""
    dirs = imaginary_directions(nbases=2, order=4)
    factor_by_bases = {d["bases"]: d["factor"] for d in dirs}
    assert factor_by_bases[(1,)] == 1
    assert factor_by_bases[(1, 1)] == factorial(2)
    assert factor_by_bases[(1, 2)] == 1
    assert factor_by_bases[(1, 1, 1)] == factorial(3)
    assert factor_by_bases[(1, 1, 2)] == factorial(2)
    assert factor_by_bases[(1, 2, 2)] == factorial(2)
    assert factor_by_bases[(1, 1, 1, 1)] == factorial(4)
    assert factor_by_bases[(1, 1, 2, 2)] == factorial(2) * factorial(2)
    assert factor_by_bases[(1, 2, 2, 2)] == factorial(3)
    assert factor_by_bases[(2, 2, 2, 2)] == factorial(4)


# ---------------------------------------------------------------------------
# Fortran generation + compile + run
# ---------------------------------------------------------------------------

@REQUIRES_GFORTRAN
def test_generated_fortran_compiles_and_extracts_orders_1_to_4(tmp_path: Path):
    model = HigherOrderModel.softwarex_bivariate_quintic()
    layout = generate_higher_order_build(tmp_path / "build", model)

    # Emitted files must exist and be non-empty.
    for path in (
        layout.master_parameters,
        layout.real_utils,
        layout.otim_module,
        layout.response,
        layout.driver,
        layout.makefile,
        layout.directions_csv,
    ):
        assert path.is_file(), path
        assert path.stat().st_size > 0

    exe = compile_higher_order_build(layout)
    result = run_higher_order_driver(exe)
    assert result.returncode == 0, result.stderr
    assert result.coefficients_csv.is_file()
    assert result.derivatives_csv.is_file()

    analytical = analytical_derivatives(model)
    recovered = read_derivatives_csv(result.derivatives_csv)

    # Every direction the enumeration expects must be present in the driver
    # output, and every value must match SymPy to at least 1e-10 relative on
    # this scaled polynomial model.
    assert set(analytical) == set(recovered)
    max_rel = 0.0
    for multiset, ana in analytical.items():
        oti = recovered[multiset]["recovered_derivative"]
        scale = max(abs(ana), abs(oti), 1.0)
        rel = abs(ana - oti) / scale
        assert rel < 1.0e-10, (multiset, ana, oti, rel)
        if rel > max_rel:
            max_rel = rel

    # The driver's recovery factor must exactly match the canonical table.
    for multiset, entry in recovered.items():
        expected_factor = 1
        from collections import Counter
        for m in Counter(multiset).values():
            expected_factor *= factorial(m)
        assert entry["recovery_factor"] == expected_factor


@REQUIRES_GFORTRAN
def test_directions_csv_is_deterministic(tmp_path: Path):
    model = HigherOrderModel.softwarex_bivariate_quintic()
    layout_a = generate_higher_order_build(tmp_path / "a", model)
    layout_b = generate_higher_order_build(tmp_path / "b", model)
    assert layout_a.directions_csv.read_bytes() == layout_b.directions_csv.read_bytes()


@REQUIRES_GFORTRAN
def test_raw_coefficient_equals_derivative_divided_by_factor(tmp_path: Path):
    """Raw OTI coefficient stored by the module must equal the true
    derivative divided by the direction's factorial recovery factor.
    """
    model = HigherOrderModel.softwarex_bivariate_quintic()
    layout = generate_higher_order_build(tmp_path / "build", model)
    exe = compile_higher_order_build(layout)
    result = run_higher_order_driver(exe)
    analytical = analytical_derivatives(model)
    recovered = read_derivatives_csv(result.derivatives_csv)
    for multiset, ana in analytical.items():
        entry = recovered[multiset]
        expected_raw = ana / entry["recovery_factor"]
        assert entry["raw_coefficient"] == pytest.approx(expected_raw, rel=1e-10, abs=1e-12)
