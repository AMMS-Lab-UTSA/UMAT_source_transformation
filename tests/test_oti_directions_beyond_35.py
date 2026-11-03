"""OTI modules past 35 directions, and the limits the generator does enforce.

The upstream writer names a direction by one character per basis from a
36-symbol alphabet ('0'-'9', 'A'-'Z'), so a 36th direction once stopped
generation with "list index out of range" (RR#43 of the SoftwareX audit).
Bases from 36 up are now written ``_<decimal>_``. These tests hold three
things at once:

* nothing changes for a module of up to 35 directions -- the names are the
  upstream ones and the constant block is written byte-for-byte as the vendored
  writer writes it;
* past 35 the names stay unique, legal Fortran, and actually carry the right
  derivative through compiled arithmetic (a compile-and-run check, skipped
  without gfortran);
* a request past a real limit is refused before any file is written, with the
  numbers, rather than producing something that looks generated.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from itertools import combinations_with_replacement
from pathlib import Path

import pytest

from umat_oti.oti import oti_directions as dirs
from umat_oti.oti.module_generator import (
    DEFAULT_MAX_COEFFICIENTS,
    OtilibSizeLimitError,
    _install_pyoti_shim,
    _set_type_constants_linear,
    check_otilib_module_size,
    generate_otilib_module,
    otilib_coefficient_count,
)
from umat_oti.transform.parameter_sensitivity_transform import oti_direction_names

FORTRAN_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _scan_fulldir(idx: int, order: int) -> tuple[int, ...]:
    """The original linear-scan definition, kept here as the reference."""
    for i, direction in enumerate(dirs._gen_dirs(order)):
        if i == idx:
            return direction
    raise AssertionError("unreachable for order >= 1")


# ---------------------------------------------------------------------------
# Naming at and past the 35/36 boundary
# ---------------------------------------------------------------------------

def test_the_last_alphabet_name_and_the_first_delimited_name():
    assert dirs.member_name([35]) == "EZ"
    assert dirs.member_name([36]) == "E_36_"
    assert dirs.member_name([1, 36]) == "E1_36_"
    assert dirs.member_name([36, 36]) == "E_36__36_"
    assert dirs.member_name([3, 6]) == "E36"  # two small bases, not base 36


def test_names_up_to_35_are_the_upstream_single_characters():
    upstream = [chr(i) for i in range(48, 58)] + [chr(i) for i in range(65, 91)]
    assert [dirs.basis_token(b) for b in range(36)] == upstream


@pytest.mark.parametrize("nbases,order", [(303, 1), (60, 2), (40, 3), (20, 4)])
def test_member_names_are_unique_legal_fortran_and_case_insensitively_distinct(nbases, order):
    names = [d["name"] for d in dirs.imaginary_directions(nbases, order)]
    assert len(names) == otilib_coefficient_count(nbases, order) - 1
    assert all(FORTRAN_NAME.match(n) for n in names)
    assert max(len(n) for n in names) == dirs.max_member_name_length(nbases, order)
    assert max(len(n) for n in names) <= dirs.FORTRAN_MAX_NAME_LENGTH
    upper = {n.upper() for n in names}
    assert len(upper) == len(names)
    # No member may shadow the real part.
    assert "R" not in upper


def test_a_negative_basis_is_an_error_not_a_wrapped_index():
    with pytest.raises(ValueError):
        dirs.basis_token(-1)


def test_parameter_sensitivity_seeds_use_the_delimited_names():
    names = oti_direction_names(40)
    assert names[34] == "EZ"
    assert names[35] == "E_36_"
    assert names[39] == "E_40_"


# ---------------------------------------------------------------------------
# Enumeration: the memoised index is the scan
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("order,count", [(1, 400), (2, 900), (3, 700), (4, 500)])
def test_memoised_fulldir_matches_the_linear_scan(order, count):
    for idx in range(count):
        assert dirs.fulldir(idx, order) == _scan_fulldir(idx, order)


@pytest.mark.parametrize("nbases,order", [(50, 1), (40, 2), (15, 3), (9, 4)])
def test_dir_index_inverts_fulldir_and_covers_exactly_the_multisets(nbases, order):
    expected = set(combinations_with_replacement(range(1, nbases + 1), order))
    seen = {dirs.fulldir(i, order) for i in range(dirs.ndir_order(nbases, order))}
    assert seen == expected
    for multiset in expected:
        assert dirs.fulldir(dirs.dir_index(multiset), order) == multiset
    # The index is of the multiset: the order the bases are listed in does not matter.
    for multiset in sorted(expected)[:50]:
        assert dirs.dir_index(tuple(reversed(multiset))) == dirs.dir_index(multiset)


def test_dir_index_rejects_a_basis_below_one():
    with pytest.raises(ValueError):
        dirs.dir_index((0, 2))


def test_fulldir_order_zero_and_negative_index():
    assert dirs.fulldir(0, 0) == ()
    with pytest.raises(IndexError):
        dirs.fulldir(1, 0)
    with pytest.raises(IndexError):
        dirs.fulldir(-1, 1)


# ---------------------------------------------------------------------------
# Constant block: the linear writer is the vendored writer
# ---------------------------------------------------------------------------

def _vendored_writer_class():
    support = Path(__file__).resolve().parents[1] / "src" / "umat_oti" / "oti" / "support"
    template_dir = support / "pyoti_templates"
    modules = _install_pyoti_shim(template_dir)
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        spec = importlib.util.spec_from_file_location("vendored_fmod_writer_for_test",
                                                      support / "fmod_writer.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
    return module


@pytest.mark.parametrize("nbases,order", [
    (1, 1), (6, 1), (35, 1), (36, 1), (37, 1), (120, 1),
    (2, 2), (6, 2), (35, 2), (36, 2), (40, 2),
    (6, 3), (12, 3), (6, 4), (8, 4),
])
def test_linear_constant_block_is_byte_identical_to_the_vendored_one(nbases, order):
    module = _vendored_writer_class()
    module.valid_chars = [dirs.basis_token(b) for b in range(max(36, nbases + 1))]
    writer = module.writer(nbases=nbases, order=order, coeff_type="REAL(DP)")
    vendored = module.writer.set_type_constants(writer, level="  ")
    assert _set_type_constants_linear(writer, level="  ") == vendored


# ---------------------------------------------------------------------------
# Generation past 35, and refusal past real limits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nbases", [36, 200])
def test_generation_past_35_directions_writes_the_delimited_members(tmp_path, nbases):
    result = generate_otilib_module(output_dir=tmp_path, ntens=nbases, order=1)
    text = result.module_path.read_text(encoding="utf-8")
    declared = re.findall(r"^\s*REAL\(DP\) :: (E\w+)\s*$", text, re.MULTILINE)
    assert declared == [dirs.member_name([b]) for b in range(1, nbases + 1)]
    assert declared[34:36] == ["EZ", "E_36_"]
    assert f"TYPE({result.type_name}), PARAMETER :: E_{nbases}_ = " in text


def test_a_coefficient_count_past_the_limit_is_refused_before_writing(tmp_path):
    out = tmp_path / "refused"
    count = otilib_coefficient_count(200, 2)
    assert count == 20301 > DEFAULT_MAX_COEFFICIENTS
    with pytest.raises(OtilibSizeLimitError, match=r"20301 coefficients"):
        generate_otilib_module(output_dir=out, ntens=200, order=2)
    assert not out.exists()


def test_the_limit_can_be_raised_explicitly_and_lowered_by_environment(monkeypatch):
    assert check_otilib_module_size(200, 2, max_coefficients=30000) == 20301
    monkeypatch.setenv("UMAT_OTI_MAX_COEFFICIENTS", "100")
    with pytest.raises(OtilibSizeLimitError):
        check_otilib_module_size(20, 2)
    assert check_otilib_module_size(20, 2, max_coefficients=231) == 231
    monkeypatch.setenv("UMAT_OTI_MAX_COEFFICIENTS", "lots")
    with pytest.raises(OtilibSizeLimitError, match="integer"):
        check_otilib_module_size(2, 1)


def test_a_basis_past_the_representable_index_is_refused():
    with pytest.raises(OtilibSizeLimitError, match="basis index"):
        check_otilib_module_size(dirs.MAX_BASIS_INDEX + 1, 1, max_coefficients=10**9)
    assert check_otilib_module_size(dirs.MAX_BASIS_INDEX, 1, max_coefficients=10**9) \
        == dirs.MAX_BASIS_INDEX + 1


def test_the_refused_sizes_are_the_ones_the_count_says():
    # Order one stays far below the default at every direction count a UMAT has.
    assert check_otilib_module_size(1000, 1) == 1001
    assert check_otilib_module_size(139, 2) == 9870
    with pytest.raises(OtilibSizeLimitError):
        check_otilib_module_size(140, 2)
    with pytest.raises(OtilibSizeLimitError):
        check_otilib_module_size(40, 3)  # 12341 coefficients


# ---------------------------------------------------------------------------
# Compiled arithmetic past 35 directions
# ---------------------------------------------------------------------------

DRIVER = """\
PROGRAM BEYOND_35
  USE master_parameters, ONLY: DP
  USE {module}
  IMPLICIT NONE
  TYPE({type_name}) :: X1, X35, X36, X40, F
  REAL(DP) :: EXPECT(4), GOT(4)
  X1  = 1.5_DP + E1
  X35 = 0.7_DP + EZ
  X36 = 2.0_DP + E_36_
  X40 = 0.3_DP + E_40_
  F = X1*X36 + SIN(X40)*X35
  ! dF/dx1 = x36, dF/dx35 = sin(x40), dF/dx36 = x1, dF/dx40 = cos(x40)*x35
  EXPECT = [2.0_DP, SIN(0.3_DP), 1.5_DP, COS(0.3_DP)*0.7_DP]
  GOT = [F%E1, F%EZ, F%E_36_, F%E_40_]
  WRITE(*,'(A,ES24.16)') 'REAL ', F%R
  IF (ABS(F%R - (3.0_DP + SIN(0.3_DP)*0.7_DP)) > 1.0E-14_DP) STOP 2
  IF (ANY(ABS(GOT - EXPECT) > 1.0E-14_DP)) STOP 3
  IF (ABS(F%E2) + ABS(F%E_37_) + ABS(F%E_39_) /= 0.0_DP) STOP 4
  WRITE(*,'(A)') 'OK'
END PROGRAM BEYOND_35
"""


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_40_direction_module_compiles_and_carries_each_derivative(tmp_path):
    result = generate_otilib_module(output_dir=tmp_path, ntens=40, order=1)
    (tmp_path / "beyond_35.f90").write_text(
        DRIVER.format(module=result.module_name, type_name=result.type_name), encoding="utf-8")
    flags = ["-O0", "-ffree-line-length-none"]
    for unit in ("master_parameters.f90", "real_utils.f90", result.module_path.name, "beyond_35.f90"):
        subprocess.run(["gfortran", *flags, "-c", unit], cwd=tmp_path, check=True,
                       capture_output=True, text=True)
    exe = tmp_path / "beyond_35.exe"
    objs = ["master_parameters.o", "real_utils.o", f"{result.module_name}.o", "beyond_35.o"]
    subprocess.run(["gfortran", *objs, "-o", str(exe)], cwd=tmp_path, check=True,
                   capture_output=True, text=True)
    run = subprocess.run([str(exe)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK" in run.stdout
