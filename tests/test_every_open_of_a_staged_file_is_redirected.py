"""``redirect`` pointed only the FIRST statement that opens a file at the staged
copy. The Jacobian-matched bundle holds two copies of the author's routine, so
the second still opened 'C:\\Users\\...\\E0.CSV' in the solver's scratch
directory and aborted in for_open (pass22: Hunman_face, Mesh_Convergence
Alex/20470 and Alex/749, TendrilOfPumpkin -- recorded as primal_disagreed).
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.data_files import opened_files, redirect
from umat_oti.abaqus.replay import jacobian_matched_source

pytestmark = pytest.mark.unit

ROUTINE = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)
        open(301,FILE='C:\\Users\\12872\\Desktop\\'//
     &  'Human_face\\E0.CSV',status="old")
        read(301,*) E0
        close(301)
        open(302,FILE='table.dat',status='old')
        close(302)
        RETURN
      END
"""


def _joined(text):
    return text.replace("\n     &", "").replace("'//'", "")


def test_a_file_opened_in_two_places_is_pointed_in_both():
    text = ROUTINE + "\n" + ROUTINE.replace("UMAT", "OTHER")
    out, pointed = redirect(text, Path("/work/job"),
                            staged=[o.name for o in opened_files(text)])
    joined = _joined(out)
    assert joined.count("/work/job/C:\\Users\\12872\\Desktop\\Human_face\\E0.CSV") == 2
    assert joined.count("/work/job/table.dat") == 2
    assert "'C:\\Users" not in joined and "'Human_face" not in joined
    assert set(pointed) == {"C:\\Users\\12872\\Desktop\\Human_face\\E0.CSV", "table.dat"}


def test_both_copies_of_the_jacobian_matched_bundle_are_redirected():
    bundle, note = jacobian_matched_source(ROUTINE, ROUTINE, "fixed")
    assert all(note["entry_renamed"].values())
    out, _ = redirect(bundle, Path("/work/job"),
                      staged=[o.name for o in opened_files(bundle)])
    assert _joined(out).count("/work/job/C:\\Users\\12872\\Desktop\\Human_face\\E0.CSV") == 2
    assert "'C:\\Users" not in _joined(out)


def test_a_single_open_is_unchanged_in_behaviour():
    out, pointed = redirect(ROUTINE, Path("/work/job"),
                            staged=[o.name for o in opened_files(ROUTINE)])
    assert _joined(out).count("/work/job/C:\\Users\\12872\\Desktop\\Human_face\\E0.CSV") == 1
    assert len(pointed) == 2
