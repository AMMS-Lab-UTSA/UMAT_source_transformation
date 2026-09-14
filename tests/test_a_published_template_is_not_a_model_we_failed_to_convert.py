"""A file with the interface and no model is not this project's failure.

``matmodlab2/matmodlab2/umat/umat_stub.f90`` is 22 lines. The
``ufc-fem-kernel`` adapter is 55, and its body is a single
``PRINT '[UMAT] Adapter stub'``. Both present the 37-argument UMAT header, both
assign neither ``STRESS`` nor ``DDSDDE`` anywhere, and neither makes a single
``CALL``. There is no constitutive model in either of them.

Both were sitting at ``transform_refused``, which is INTERNAL and says this
project could not convert somebody's model. ``incomplete_or_corrupt_source``
was the near miss and would have been worse: it is glossed "does not compile",
and a template compiles perfectly well.

Agent A found these and left them INTERNAL rather than borrow a state that
would have made the report say something false -- the safe direction, and the
right call while the state did not exist. It exists now.
"""
from umat_oti.abaqus import terminal_states as ts

STUB = "published_stub_no_constitutive_content"


def test_a_published_template_is_external():
    """The work that is missing is the author's, not ours."""
    assert STUB in ts.EXTERNAL
    assert ts.kind_of(STUB) == "external"
    assert ts.from_stage(STUB).finished is True


def test_it_is_not_filed_as_something_this_project_could_not_convert():
    assert STUB not in ts.INTERNAL
    assert ts.kind_of("transform_refused") == "internal"


def test_it_is_not_filed_as_a_file_that_does_not_compile():
    """The near miss, and the reason it is wrong: a template compiles."""
    assert STUB != "incomplete_or_corrupt_source"
    assert ts.kind_of("incomplete_or_corrupt_source") == "external"
    # both external, so the distinction is not about whose column it lands in;
    # it is about the sentence the report prints next to the source.
    assert ts.from_stage(STUB).state != ts.from_stage(
        "incomplete_or_corrupt_source").state


def test_the_batch_vocabulary_translates_it():
    assert ts.FROM_STAGE[STUB] == STUB
    assert STUB in ts.ALL


def test_every_state_in_all_has_exactly_one_kind():
    """The guard that stops a state being added to two lists at once."""
    assert len(ts.ALL) == len(set(ts.ALL))
    for state in ts.ALL:
        assert ts.kind_of(state) in ("verified", "external", "internal")
    assert not set(ts.EXTERNAL) & set(ts.INTERNAL)


def test_every_translated_stage_lands_on_a_state_that_exists():
    for stage, state in ts.FROM_STAGE.items():
        assert state in ts.ALL, f"{stage} -> {state}"
