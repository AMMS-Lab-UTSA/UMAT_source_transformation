"""The Abaqus UMAT interface is positional, and so is its stress update.

``sahmotaman/TMM-FE-Simulation`` writes ``subroutine umat(sigma, sv, C, ...)``
and assigns ``sigma`` and ``C``. A search for assignments to the literal names
STRESS and DDSDDE found nothing, so the registry recorded four genuine UMATs
as files with no stress update anywhere -- while the classifier, which already
reads the interface by position, called them genuine. Two artefacts disagreed
about the same file.

Measured over all 391 sources: five change, all from "writes nothing" to
"writes both" or "writes stress". The first version of the fix also changed
adtzlr/ttb, whose ``umat(Siso_arr, C4iso_arr, F_arr, E_arr)`` is a four-argument
routine of its own that shares the name. That was a false positive and is why
the mapping applies only to a unit matching the interface's argument count.
"""
from umat_oti.corpus.entry_routines import umat_outputs_written

HEADER = ("      SUBROUTINE UMAT({s},STATEV,{d},SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,\n"
          "     1 DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,\n"
          "     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,\n"
          "     3 PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)\n")


def _umat(stress_name, ddsdde_name, body):
    return (HEADER.format(s=stress_name, d=ddsdde_name) + body
            + "      RETURN\n      END\n")


def test_the_authors_own_names_for_the_outputs_are_found():
    source = _umat("SIGMA", "CMAT", "      SIGMA(1) = 1.0D0\n"
                                     "      CMAT(1,1) = 2.0D0\n")
    found = umat_outputs_written(source, form="fixed")
    assert found.writes_stress and found.writes_ddsdde


def test_the_canonical_names_still_count():
    source = _umat("STRESS", "DDSDDE", "      STRESS(1) = 1.0D0\n"
                                       "      DDSDDE(1,1) = 2.0D0\n")
    found = umat_outputs_written(source, form="fixed")
    assert found.writes_stress and found.writes_ddsdde


def test_a_routine_named_umat_with_its_own_arguments_is_not_mapped():
    """ttb's four-argument ``umat`` has no positional stress: its first
    argument is whatever its author meant, and reading it as STRESS would
    call a file a stress update on the strength of a shared name."""
    source = ("      SUBROUTINE UMAT(SISO,C4ISO,F,E)\n"
              "      SISO(1) = 1.0D0\n"
              "      RETURN\n      END\n")
    found = umat_outputs_written(source, form="fixed")
    assert not found.writes_stress and not found.writes_ddsdde


def test_a_local_with_the_same_name_in_another_routine_does_not_count():
    """The author's name is the output only inside the UMAT itself."""
    source = (_umat("SIGMA", "CMAT", "      CALL HELPER\n")
              + "      SUBROUTINE HELPER\n      SIGMA(1) = 1.0D0\n"
                "      CMAT(1,1) = 2.0D0\n      RETURN\n      END\n")
    found = umat_outputs_written(source, form="fixed")
    assert not found.writes_stress and not found.writes_ddsdde
