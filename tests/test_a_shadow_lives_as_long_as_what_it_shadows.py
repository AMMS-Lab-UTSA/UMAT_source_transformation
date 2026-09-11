"""A shadow's lifetime has to match the variable it shadows.

Growth-Alex.for reads twelve tables of 7963 values on its FIRST call, SAVEs
them, and guards the read with a counter so no later call repeats it:

    data iread /1/
    SAVE iread
    SAVE Lambda1z0Imp
    ...
    IF (iread .EQ. 1) THEN
      open(301,...); read(301,*) Lambda1z0Imp; close(301)
      ...
      iread=2
    END IF

The shadows beside those arrays were declared as ordinary locals and zeroed
at every entry, and filled only inside the guard. So on call one they held
the data and on every call after it they held zero, while the author's own
arrays held the data throughout. The ORIGINAL ran all 280 increments with
finite stresses; the converted build was NaN at its first recorded
increment, because an increment takes several calls.

The fix is not a special case for SAVE: it is that a shadow persists exactly
when the thing it shadows does. DATA initialisation implies SAVE in a
subprogram, a bare SAVE saves the whole routine, and a COMMON block lives
for the whole program.
"""
from umat_oti.transform.source_transform import (_persisting_variables,
                                                 _persists)


def test_an_explicit_save_persists():
    assert _persisting_variables("      SAVE Lambda1z0Imp\n") == {"LAMBDA1Z0IMP"}


def test_data_initialisation_implies_save():
    assert "IREAD" in _persisting_variables("      data iread /1/\n")


def test_a_bare_save_saves_everything():
    persisting = _persisting_variables("      SAVE\n")
    assert persisting == {"*"}
    assert _persists("ANYTHING", persisting)


def test_a_common_block_persists():
    assert _persisting_variables("      COMMON /BLK/ A, B\n") == {"A", "B"}


def test_an_ordinary_local_does_not():
    assert _persisting_variables("      X = 1.0\n") == set()
    assert not _persists("X", set())
    assert not _persists("X", {"Y"})


def test_a_save_list_with_a_double_colon_is_read():
    assert _persisting_variables("      SAVE :: A, B\n") == {"A", "B"}


def test_an_array_in_a_save_list_loses_its_subscripts():
    assert _persisting_variables("      SAVE TABLE(3), OTHER\n") == \
        {"TABLE", "OTHER"}


def test_the_generated_source_saves_the_shadow_and_stops_zeroing_it():
    """The two halves together: declaring it SAVE and leaving it alone."""
    import re

    from umat_oti.transform.source_transform import (_declaration_lines,
                                                     _initialization_lines)
    persisting = {"TABLE"}
    declared = "\n".join(_declaration_lines(
        "fixed", "ONUMM6N1", ["TABLE", "SCRATCH"],
        {"TABLE": "7963", "SCRATCH": "6"},
        persisting_variables=persisting))
    assert re.search(r"SAVE TABLE_OTI", declared)
    assert not re.search(r"SAVE SCRATCH_OTI", declared)

    started = "\n".join(_initialization_lines(
        "fixed", {}, {"seed": set(), "promote": set()}, 6,
        ["TABLE", "SCRATCH"], {"TABLE": "7963", "SCRATCH": "6"},
        set(), set(), persisting_variables=persisting))
    assert "TABLE_OTI" not in started, (
        "a shadow that persists must not be zeroed at every entry -- the "
        "value it carries is the whole point of the SAVE")
    assert "SCRATCH_OTI" in started
