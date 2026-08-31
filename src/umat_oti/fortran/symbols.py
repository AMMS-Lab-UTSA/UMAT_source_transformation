from __future__ import annotations

from umat_oti.core.model import Declaration, ParsedFortranSource, ParsedSubroutine


def declaration_map(routine: ParsedSubroutine) -> dict[str, Declaration]:
    result: dict[str, Declaration] = {}
    for declaration in routine.declarations:
        for entity in declaration.entities:
            result[entity.upper_name] = declaration
    return result


def entity_dimension_map(routine: ParsedSubroutine) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for declaration in routine.declarations:
        for entity in declaration.entities:
            result[entity.upper_name] = entity.dimensions
    return result


def routine_symbol_names(routine: ParsedSubroutine) -> set[str]:
    """Every name this routine itself introduces: dummy arguments and declared entities.

    Which variable a routine can be seeded through is a fact about that
    routine's own interface, not about the file it sits in. Keeping the Abaqus
    interface separate from the constitutive model is ordinary practice:
    ``subroutine umat(...)`` declares the full Abaqus argument list and hands
    the work to a model routine, passing only the arguments that model needs.
    For a finite-strain material that is the deformation gradient and not the
    strain increment. Reading the file's UMAT signature instead concludes that
    DSTRAN is available inside a routine that never receives it, and the
    emitted ``DSTRAN_OTI`` is then an undeclared name that ``implicit none``
    rejects.
    """
    names = {str(argument).upper() for argument in routine.args}
    names.update(declaration_map(routine))
    return names


def find_routine(
    parsed: ParsedFortranSource, name: str
) -> ParsedSubroutine | None:
    """The parsed routine with this name, or None when the source has no such routine."""
    wanted = str(name).upper()
    for routine in parsed.subroutines:
        if routine.upper_name == wanted:
            return routine
    return None
