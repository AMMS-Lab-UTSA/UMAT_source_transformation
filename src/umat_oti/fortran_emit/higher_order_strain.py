"""Higher-order OTI Fortran driver generator (orders 1..4).

Priority 3 of the SoftwareX continuation: produce compilable OTI Fortran that
extracts mixed and repeated higher-order derivatives of a scalar-valued
response ``sigma`` with respect to strain-like independent variables, and
verify the recovered derivatives against SymPy analytical differentiation.

The emitter is intentionally scoped to a *small* nbases (2 by default) so:

* every mixed and repeated direction is exercised (mixed-direction and
  repeated-direction enumeration is the interesting bit; single-basis
  cases are degenerate),
* the emitted Fortran compiles quickly on gfortran,
* the SymPy-vs-OTI verification runs in offline CI without waiting on a
  30 000-line ``otim6n4`` module.

The same emitter mechanism works for larger ``(nbases, order)`` pairs, but
the compile time grows super-linearly. See ``generate_higher_order_build``
for details.

Fortran layout produced by ``generate_higher_order_build``::

    <dir>/master_parameters.f90
    <dir>/real_utils.f90
    <dir>/otim<nbases>n<order>.f90     (via umat_oti.oti.module_generator)
    <dir>/nonlinear_response.f90        (the scalar sigma(x_1..x_nbases))
    <dir>/higher_order_driver.f90       (seeds, calls, GETIM extracts)
    <dir>/Makefile
    <dir>/higher_order_directions.csv   (documenting the enumeration)
"""

from __future__ import annotations

import csv
import shutil
import subprocess
from dataclasses import dataclass
from math import factorial
from pathlib import Path
from typing import Iterable, Optional

import sympy as sp

from umat_oti.oti.module_generator import generate_otilib_module
from umat_oti.oti.oti_directions import imaginary_directions, member_name


@dataclass
class HigherOrderModel:
    """A scalar model over ``nbases`` independent variables.

    ``expression`` is a SymPy expression in the symbols ``x[0], x[1], ...``.
    ``operating_point`` is the numeric value of each independent variable at
    which we seed the OTI directions and evaluate the analytical reference.
    """

    nbases: int
    order: int
    x: list[sp.Symbol]
    expression: sp.Expr
    operating_point: list[float]
    label: str = "nonlinear"

    @classmethod
    def softwarex_bivariate_quintic(cls) -> "HigherOrderModel":
        """A generic bivariate polynomial with every derivative <= 4 non-zero.

        ``sigma(x, y) = x + 2*y + 3*x*y + 5*x**2 - 7*y**2 + 11*x**3
        - 13*x**2*y + 17*x*y**2 - 19*y**3 + 23*x**4 - 29*x**3*y +
        31*x**2*y**2 - 37*x*y**3 + 41*y**4``.
        """
        x, y = sp.symbols("x y")
        expr = (
            x + 2 * y + 3 * x * y + 5 * x ** 2 - 7 * y ** 2
            + 11 * x ** 3 - 13 * x ** 2 * y + 17 * x * y ** 2 - 19 * y ** 3
            + 23 * x ** 4 - 29 * x ** 3 * y + 31 * x ** 2 * y ** 2
            - 37 * x * y ** 3 + 41 * y ** 4
        )
        return cls(
            nbases=2,
            order=4,
            x=[x, y],
            expression=expr,
            operating_point=[0.1, 0.05],
            label="bivariate_quintic",
        )


@dataclass
class HigherOrderBuildLayout:
    root: Path
    master_parameters: Path
    real_utils: Path
    otim_module: Path
    response: Path
    driver: Path
    makefile: Path
    directions_csv: Path
    module_name: str


@dataclass
class HigherOrderRunResult:
    executable: Path
    returncode: int
    stdout: str
    stderr: str
    coefficients_csv: Path
    derivatives_csv: Path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_higher_order_build(
    output_dir: Path | str,
    model: HigherOrderModel,
) -> HigherOrderBuildLayout:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    module_result = generate_otilib_module(
        output_dir=output_dir, ntens=model.nbases, order=model.order
    )

    response_path = output_dir / "nonlinear_response.f90"
    response_path.write_text(_response_source(model, module_result.module_name), encoding="utf-8")

    driver_path = output_dir / "higher_order_driver.f90"
    driver_path.write_text(
        _driver_source(model, module_result.module_name, module_result.type_name),
        encoding="utf-8",
    )

    makefile_path = output_dir / "Makefile"
    makefile_path.write_text(_makefile_source(module_result.module_name), encoding="utf-8")

    directions_csv = output_dir / "higher_order_directions.csv"
    _write_directions_csv(directions_csv, model)

    return HigherOrderBuildLayout(
        root=output_dir,
        master_parameters=module_result.master_parameters_path,
        real_utils=module_result.real_utils_path,
        otim_module=module_result.module_path,
        response=response_path,
        driver=driver_path,
        makefile=makefile_path,
        directions_csv=directions_csv,
        module_name=module_result.module_name,
    )


def compile_higher_order_build(
    layout: HigherOrderBuildLayout, *, gfortran: str = "gfortran"
) -> Path:
    if shutil.which(gfortran) is None:
        raise RuntimeError(
            f"Fortran compiler {gfortran!r} not on PATH."
        )
    proc = subprocess.run(
        ["make", f"FC={gfortran}"],
        cwd=str(layout.root),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gfortran build failed:\n{proc.stdout}\n{proc.stderr}")
    exe = layout.root / "higher_order_driver"
    if not exe.is_file():
        raise RuntimeError(f"driver executable not produced at {exe}")
    return exe


def run_higher_order_driver(
    executable: Path, *, out_dir: Optional[Path] = None
) -> HigherOrderRunResult:
    out_dir = Path(out_dir) if out_dir is not None else executable.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(executable)],
        cwd=str(out_dir),
        check=False,
        capture_output=True,
        text=True,
    )
    return HigherOrderRunResult(
        executable=executable,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        coefficients_csv=out_dir / "higher_order_coefficients.csv",
        derivatives_csv=out_dir / "higher_order_derivatives.csv",
    )


def analytical_derivatives(model: HigherOrderModel) -> dict[tuple[int, ...], float]:
    """Return ``{multiset_of_1_based_bases: analytical partial derivative}``.

    Uses SymPy to differentiate ``model.expression`` and evaluate at the
    operating point.
    """
    subs = {sym: val for sym, val in zip(model.x, model.operating_point)}
    results: dict[tuple[int, ...], float] = {}
    for entry in imaginary_directions(model.nbases, model.order):
        multiset = tuple(entry["bases"])
        expr = model.expression
        for basis in multiset:
            expr = sp.diff(expr, model.x[basis - 1])
        value = float(sp.N(expr.subs(subs)))
        results[multiset] = value
    return results


def read_derivatives_csv(path: Path) -> dict[tuple[int, ...], dict]:
    """Read the driver's ``higher_order_derivatives.csv`` back into a dict."""
    out: dict[tuple[int, ...], dict] = {}
    with Path(path).open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        for entry in reader:
            multiset = tuple(int(v) for v in entry[3].split("|") if v)
            out[multiset] = {
                "order": int(entry[0]),
                "name": entry[1],
                "flat_index": int(entry[2]),
                "raw_coefficient": float(entry[4]),
                "recovery_factor": int(entry[5]),
                "recovered_derivative": float(entry[6]),
            }
    return out


# ---------------------------------------------------------------------------
# Fortran generation
# ---------------------------------------------------------------------------

def _write_directions_csv(path: Path, model: HigherOrderModel) -> None:
    """Emit the deterministic direction enumeration + recovery factors."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["order", "member_name", "flat_getim_index", "bases_multiindex", "recovery_factor"]
        )
        for entry in imaginary_directions(model.nbases, model.order):
            writer.writerow(
                [
                    entry["order"],
                    entry["name"],
                    entry["flat"],
                    "|".join(str(b) for b in entry["bases"]),
                    entry["factor"],
                ]
            )


def _sympy_to_fortran_oti(
    expr: sp.Expr, x: list[sp.Symbol], type_name: str
) -> str:
    """Convert a SymPy expression to a Fortran expression using OTI arithmetic.

    Integer numeric coefficients are converted to ``REAL(DP)`` literals with
    an explicit ``_DP`` kind marker so that ``k*X`` composes with the OTI
    module's ``REAL(DP) * ONUMM<*>`` overload -- the module deliberately does
    not overload ``INTEGER * ONUMM``. Exponents in ``X**k`` also become
    ``REAL(DP)`` and are handled by the ``POW_OR`` overload.
    """
    import re
    subs = {sym: sp.Symbol(f"X{i + 1}") for i, sym in enumerate(x)}
    substituted = expr.subs(subs)
    fortran = sp.fcode(substituted, source_format="free", standard=2008)
    fortran = fortran.replace("      ", "")
    fortran = fortran.replace("&\n", " ")
    # Tag every integer literal not already carrying a decimal point / exponent.
    fortran = re.sub(
        r"(?<![\w.])(\d+)(?![\w.\d])",
        lambda m: f"{m.group(0)}.0_DP",
        fortran,
    )
    return fortran.strip()


def _response_source(model: HigherOrderModel, module_name: str) -> str:
    type_name = f"ONUMM{model.nbases}N{model.order}"
    input_args = ", ".join(f"X{i + 1}" for i in range(model.nbases))
    input_decls = "\n    ".join(
        f"TYPE({type_name}), INTENT(IN) :: X{i + 1}" for i in range(model.nbases)
    )
    body = _sympy_to_fortran_oti(model.expression, model.x, type_name)
    return f"""!===============================================================
! Non-linear scalar response sigma({input_args}) implemented on OTI numbers.
! Generated for the SoftwareX higher-order strain-derivative demonstrator.
!===============================================================
MODULE nonlinear_response_mod
  USE master_parameters, ONLY: DP
  USE {module_name}
  IMPLICIT NONE
  PRIVATE
  PUBLIC :: sigma_response

CONTAINS

  FUNCTION sigma_response({input_args}) RESULT(SIGMA)
    {input_decls}
    TYPE({type_name}) :: SIGMA

    SIGMA = {body}
  END FUNCTION sigma_response

END MODULE nonlinear_response_mod
"""


def _driver_source(model: HigherOrderModel, module_name: str, type_name: str) -> str:
    directions = imaginary_directions(model.nbases, model.order)
    inputs_seed = "\n".join(
        f"  X{i + 1} = {op:.17e}_DP + E{i + 1}"
        for i, op in enumerate(model.operating_point)
    )
    x_decls = ", ".join(f"X{i + 1}" for i in range(model.nbases))

    ext_lines = "\n".join(
        f"  coeff({idx + 1}) = GETIM(SIGMA_OTI, {entry['flat']})"
        for idx, entry in enumerate(directions)
    )
    csv_rows_coeff = "\n".join(
        f'  WRITE(U_COEF, \'(I0,A,A,A,I0,A,I0,A,ES23.15)\') '
        f'{entry["order"]}, ",", "{entry["name"]}", ",", {entry["flat"]}, ",", '
        f'{entry["factor"]}, ",", coeff({idx + 1})'
        for idx, entry in enumerate(directions)
    )
    csv_rows_deriv = "\n".join(
        f'  bases_str = "{"|".join(str(b) for b in entry["bases"])}"\n'
        f'  WRITE(U_DER, \'(I0,A,A,A,I0,A,A,A,ES23.15,A,I0,A,ES23.15)\') '
        f'{entry["order"]}, ",", "{entry["name"]}", ",", {entry["flat"]}, ",", '
        f'TRIM(bases_str), ",", coeff({idx + 1}), ",", {entry["factor"]}, ",", '
        f'coeff({idx + 1}) * REAL({entry["factor"]}, DP)'
        for idx, entry in enumerate(directions)
    )

    n_coeff = len(directions)
    return f"""!===============================================================
! Higher-order driver: seed X1..X{model.nbases} at the operating point,
! evaluate sigma using OTI arithmetic (order {model.order}), then extract
! every mixed and repeated derivative via GETIM. Apply the factorial
! recovery factor and dump both the raw coefficients and the recovered
! derivatives to CSV.
!===============================================================
PROGRAM higher_order_driver
  USE master_parameters, ONLY: DP
  USE {module_name}
  USE nonlinear_response_mod, ONLY: sigma_response
  IMPLICIT NONE

  TYPE({type_name}) :: {x_decls}, SIGMA_OTI
  REAL(DP) :: coeff({n_coeff})
  CHARACTER(len=64) :: bases_str
  INTEGER :: U_COEF, U_DER

{inputs_seed}

  SIGMA_OTI = sigma_response({x_decls})

{ext_lines}

  OPEN(NEWUNIT=U_COEF, FILE="higher_order_coefficients.csv", STATUS="REPLACE", ACTION="WRITE")
  WRITE(U_COEF, '(A)') "order,member,flat_index,recovery_factor,raw_coefficient"
{csv_rows_coeff}
  CLOSE(U_COEF)

  OPEN(NEWUNIT=U_DER, FILE="higher_order_derivatives.csv", STATUS="REPLACE", ACTION="WRITE")
  WRITE(U_DER, '(A)') "order,member,flat_index,bases_multiindex,raw_coefficient,recovery_factor,recovered_derivative"
{csv_rows_deriv}
  CLOSE(U_DER)

END PROGRAM higher_order_driver
"""


def _makefile_source(module_name: str) -> str:
    return f"""FC      ?= gfortran
FCFLAGS ?= -O1 -std=f2008 -ffree-line-length-none

.PHONY: all clean

all: higher_order_driver

master_parameters.o: master_parameters.f90
\t$(FC) $(FCFLAGS) -c $<

real_utils.o: real_utils.f90 master_parameters.o
\t$(FC) $(FCFLAGS) -c $<

{module_name}.o: {module_name}.f90 master_parameters.o real_utils.o
\t$(FC) $(FCFLAGS) -c $<

nonlinear_response.o: nonlinear_response.f90 {module_name}.o
\t$(FC) $(FCFLAGS) -c $<

higher_order_driver.o: higher_order_driver.f90 nonlinear_response.o {module_name}.o
\t$(FC) $(FCFLAGS) -c $<

higher_order_driver: master_parameters.o real_utils.o {module_name}.o nonlinear_response.o higher_order_driver.o
\t$(FC) $(FCFLAGS) $^ -o $@

clean:
\trm -f *.o *.mod higher_order_driver *.csv
"""


__all__ = [
    "HigherOrderBuildLayout",
    "HigherOrderModel",
    "HigherOrderRunResult",
    "analytical_derivatives",
    "compile_higher_order_build",
    "generate_higher_order_build",
    "read_derivatives_csv",
    "run_higher_order_driver",
]
