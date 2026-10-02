"""Loading paths for the routine-level harness.

The owner of loading paths is Curie (``loading_paths.py`` in this package,
interface agreed in ``corpus_campaign/OWNERSHIP.md``). Until that module lands
this file supplies a MINIMAL internal set -- elastic, plastic-amplitude load,
unload -- with the same shape, and :func:`paths_for` switches to Curie's module
automatically as soon as it is importable.

Shape (identical to the agreed interface)::

    LoadingPath(name, regime, kinematics, increments: list[Increment])
    Increment(dstran: tuple|None, dfgrd1: 3x3|None, dtime, temp, dtemp)

A small-strain increment carries ``dstran`` (Abaqus Voigt order 11,22,33,12,13,23
with ENGINEERING shear, truncated to ``ntens`` as ``ndi`` direct + ``nshr``
shear components). A finite-strain increment carries the deformation gradient
at the END of the increment, ``dfgrd1``; :func:`kinematics_for` derives the
DSTRAN/DROT Abaqus would pass with it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

import numpy as np

#: Abaqus Voigt order of a full 3D tensor. Shear entries are engineering
#: (gamma_ij = 2 eps_ij) in DSTRAN/STRAN, tensor in STRESS.
VOIGT_3D = ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))


@dataclass
class Increment:
    dstran: Optional[tuple] = None
    dfgrd1: Optional[tuple] = None          # 3x3 rows, END of increment
    dtime: float = 0.1
    temp: float = 293.15
    dtemp: float = 0.0


@dataclass
class LoadingPath:
    name: str
    regime: str                             # elastic|plastic|unload_reload|cyclic|relaxation|growth
    kinematics: str                         # small|finite
    increments: list = field(default_factory=list)
    provenance: str = "gauss internal minimal path (Curie's loading_paths not importable)"


def voigt_components(ndi: int, nshr: int) -> list:
    """Indices into ``VOIGT_3D`` that an (ndi, nshr) UMAT sees, in order."""
    return list(range(ndi)) + list(range(3, 3 + nshr))


def _truncate(full6: Sequence[float], ndi: int, nshr: int) -> tuple:
    return tuple(float(full6[i]) for i in voigt_components(ndi, nshr))


def _small_paths(ndi: int, nshr: int) -> list:
    # One mixed direction so every column of a 6x6 tangent is exercised:
    # extension in 11, Poisson-like contraction, and engineering shears.
    direction = (1.0, -0.3, -0.3, 0.4, 0.2, -0.1)
    elastic_amp = 2.0e-5          # 1e-4 total: elastic for any metal-like yield
    plastic_amp = 1.0e-3          # 8e-3 total: past yield for steel-like data
    elastic = [Increment(dstran=_truncate([elastic_amp * d for d in direction], ndi, nshr))
               for _ in range(5)]
    plastic = [Increment(dstran=_truncate([plastic_amp * d for d in direction], ndi, nshr))
               for _ in range(8)]
    plastic += [Increment(dstran=_truncate([-0.5 * plastic_amp * d for d in direction], ndi, nshr))
                for _ in range(4)]
    return [LoadingPath("gauss_small_elastic", "elastic", "small", elastic),
            LoadingPath("gauss_small_load_unload", "unload_reload", "small", plastic)]


def _finite_paths() -> list:
    increments = []
    for k in range(1, 7):        # isochoric-ish stretch with a little shear
        lam = 1.0 + 0.02 * k
        increments.append(Increment(dfgrd1=((lam, 0.01 * k, 0.0),
                                            (0.0, lam ** -0.5, 0.0),
                                            (0.0, 0.0, lam ** -0.5))))
    for k in range(5, 2, -1):    # partial unload
        lam = 1.0 + 0.02 * k
        increments.append(Increment(dfgrd1=((lam, 0.01 * k, 0.0),
                                            (0.0, lam ** -0.5, 0.0),
                                            (0.0, 0.0, lam ** -0.5))))
    return [LoadingPath("gauss_finite_stretch_shear_unload", "unload_reload", "finite",
                        increments)]


def internal_paths(entry: Mapping) -> list:
    ndi, nshr = int(entry.get("ndi", 3)), int(entry.get("nshr", 3))
    if str(entry.get("kinematics", "small")).startswith("finite"):
        return _finite_paths()
    return _small_paths(ndi, nshr)


def paths_for(entry: Mapping) -> list:
    """Curie's paths when available, the internal minimal ones otherwise."""
    try:
        from umat_oti.corpus_features import loading_paths as curie   # type: ignore
    except Exception:                                                   # noqa: BLE001
        return internal_paths(entry)
    try:
        paths = list(curie.paths_for(entry))
    except Exception as error:                                          # noqa: BLE001
        fallback = internal_paths(entry)
        for path in fallback:
            path.provenance += f"; curie.paths_for raised {type(error).__name__}: {error}"
        return fallback
    for path in paths:
        if not getattr(path, "provenance", ""):
            try:
                path.provenance = "curie loading_paths.paths_for"
            except Exception:                                           # noqa: BLE001
                pass
    return paths


# --------------------------------------------------------------------------
# Kinematics Abaqus would pass with a prescribed deformation gradient
# --------------------------------------------------------------------------

def strain_voigt_to_tensor(voigt: Sequence[float], ndi: int, nshr: int) -> np.ndarray:
    """Engineering-shear Voigt (ntens) -> symmetric 3x3 tensor."""
    eps = np.zeros((3, 3))
    for value, slot in zip(voigt, voigt_components(ndi, nshr)):
        i, j = VOIGT_3D[slot]
        if i == j:
            eps[i, i] += value
        else:
            eps[i, j] += 0.5 * value
            eps[j, i] += 0.5 * value
    return eps


def tensor_to_strain_voigt(eps: np.ndarray, ndi: int, nshr: int) -> list:
    out = []
    for slot in voigt_components(ndi, nshr):
        i, j = VOIGT_3D[slot]
        out.append(float(eps[i, i]) if i == j else float(eps[i, j] + eps[j, i]))
    return out


def kinematics_for(path: LoadingPath, ndi: int, nshr: int) -> list:
    """Per increment: (dstran[ntens], dfgrd0[3x3], dfgrd1[3x3], drot[3x3]).

    Small strain: ``dstran`` as prescribed; F = I + cumulative strain tensor
    (Abaqus passes F also without NLGEOM); DROT = I.

    Finite strain: F as prescribed; DSTRAN = sym(dF . F_mid^-1) in Voigt with
    engineering shear (the midpoint rate-of-deformation increment, which is
    Abaqus's strain increment to first order); DROT from the Hughes-Winget
    formula with W = skew(dF . F_mid^-1). A prescribed DSTRAN on a finite path
    is honoured as given.
    """
    out = []
    f_prev = np.eye(3)
    cumulative = np.zeros((3, 3))
    for inc in path.increments:
        if inc.dfgrd1 is not None:
            f1 = np.asarray(inc.dfgrd1, float).reshape(3, 3)
            df = f1 - f_prev
            l_inc = df @ np.linalg.inv(0.5 * (f1 + f_prev))
            d = 0.5 * (l_inc + l_inc.T)
            w = 0.5 * (l_inc - l_inc.T)
            drot = np.linalg.solve(np.eye(3) - 0.5 * w, np.eye(3) + 0.5 * w)
            dstran = (list(inc.dstran) if inc.dstran is not None
                      else tensor_to_strain_voigt(d, ndi, nshr))
        else:
            dstran = list(inc.dstran)
            cumulative = cumulative + strain_voigt_to_tensor(dstran, ndi, nshr)
            f1 = np.eye(3) + cumulative
            drot = np.eye(3)
        out.append((dstran, f_prev.copy(), f1.copy(), drot))
        f_prev = f1
    return out
