"""Fortran definitions for missing runtime utilities and numerical helpers.

DSPEVD is supplied as an independent cyclic-Jacobi implementation of the packed
symmetric interface, not a copy of LAPACK's divide-and-conquer routine. It
reports repeated/unresolved eigenvalues through INFO; callers must check it.

A UMAT may call ROTSIG to carry a state tensor through a rigid rotation. Abaqus
links that routine in; the file the author published does not define it. The
helper lifter walks CALL statements looking for a definition to lift, finds
none, and refuses the whole source -- correctly, because passing a hypercomplex
array to an un-lifted external is exactly the silent-truncation defect the
refusal exists to prevent. Eleven corpus sources stopped there.

The way out is not to exempt the call. It is to supply the definition. ROTSIG
is documented algebra -- one similarity transform on a symmetric tensor -- so
writing it out is transcribing a published interface, not reconstructing
somebody's constitutive law. Once the text is here the ordinary lifter takes
over: it transforms this body to the OTI type the same way it transforms the
author's own helpers, and the derivative flows through the rotation because a
similarity transform is bilinear in its input.

SPRINC, SPRIND and SINV (added B2, 2026-10-01). These were left out at first
because an eigenproblem's derivative is not the derivative of the algebra that
computes it once eigenvalues coincide. They are supplied now on top of the
DSPEVD body below, which handles that case deliberately: a repeated cluster is
returned averaged, so every symmetric function of the principal values
(trace, invariants, sum of Macaulay brackets, a yield surface written over
principal stresses) differentiates exactly, and an individual member of a
repeated cluster -- which has no derivative -- gets the cluster mean. A model
that reads one principal value of a repeated pair on its own (a Rankine
maximum at an exact tie) is at a kink, and the finite-difference verification
classifies it as nonsmooth rather than verifying it. Semantics follow the
Abaqus User Subroutines Reference ("Obtaining stress invariants, principal
stress/strain values and directions, and rotating tensors"):

* ``CALL SINV(STRESS, SINV1, SINV2, NDI, NSHR)``: SINV1 = tr(sigma)/3,
  SINV2 = sqrt(3/2 s:s) with s the deviator (the Mises stress). Stress-type
  storage only, as in the manual.
* ``CALL SPRINC(S, PS, LSTR, NDI, NSHR)``: PS(1..3) the principal values.
* ``CALL SPRIND(S, PS, AN, LSTR, NDI, NSHR)``: also AN(K,1..3), the direction
  cosines of the principal direction of PS(K).

S holds NDI direct components then NSHR shears ordered 12, 13, 23; LSTR=1 for
a stress-type tensor, LSTR=2 for a strain-type one whose stored shears are
engineering shears (twice the tensor entry). The manual states no ORDER for
the principal values; these return them ascending (the LAPACK convention of
DSPEVD). A model whose results depend on the order is ill-posed against the
solver's own routine, and only the Abaqus run of the transformed build (which
calls the lifted copy) against the original (which calls the solver's) can
show whether that matters; a routine-level check against the same reference
body cannot.

When a SPRINC/SPRIND/SINV/ROTSIG body is supplied, the transform calls the
LIFTED copy (``SPRINC_OTI``) and the published file keeps calling the solver's
own routine everywhere else.
"""
from __future__ import annotations

from umat_oti.transform.spectral_definitions import DSPEVD_DEFINITION
from umat_oti.transform.lu_definitions import DGETRF_DEFINITION, DGETRS_DEFINITION

#: ``CALL ROTSIG(S, R, OUTPUT, LSTR, NDI, NSHR)``
#:
#: S is a symmetric tensor in Abaqus's Voigt order: NDI direct components,
#: then NSHR shear components ordered 12, 13, 23. R is the rotation, and
#: OUTPUT receives R S R^T. LSTR says how the shear components are stored:
#: 1 for a stress-type tensor, whose off-diagonal entries ARE the shear
#: components, and 2 for a strain-type tensor, whose stored shears are
#: engineering shears -- twice the tensor entry. Getting that factor wrong
#: is a silent factor-of-two on every rotated strain, so it is applied on
#: the way in and undone on the way out rather than assumed.
#:
#: Written in fixed form with an explicit shape on every argument, so it
#: parses and lifts under the same rules as a helper the author wrote.
ROTSIG_DEFINITION = """
      SUBROUTINE ROTSIG(S, R, OUTPUT, LSTR, NDI, NSHR)
C     Abaqus utility: OUTPUT = R S R^T for a symmetric tensor in Voigt
C     storage. Supplied because the solver provides it at link time and
C     the published source therefore does not define it.
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION S(NDI+NSHR), R(3,3), OUTPUT(NDI+NSHR)
      DIMENSION T(3,3), TR(3,3)
      HALFSH = 1.0D0
      IF (LSTR .EQ. 2) HALFSH = 0.5D0
C     Voigt vector to the full symmetric tensor. Components the caller did
C     not supply are zero, which is what a reduced NDI/NSHR means.
      DO I = 1, 3
        DO J = 1, 3
          T(I,J) = 0.0D0
        END DO
      END DO
      DO I = 1, NDI
        T(I,I) = S(I)
      END DO
      IF (NSHR .GE. 1) THEN
        T(1,2) = S(NDI+1)*HALFSH
        T(2,1) = T(1,2)
      END IF
      IF (NSHR .GE. 2) THEN
        T(1,3) = S(NDI+2)*HALFSH
        T(3,1) = T(1,3)
      END IF
      IF (NSHR .GE. 3) THEN
        T(2,3) = S(NDI+3)*HALFSH
        T(3,2) = T(2,3)
      END IF
C     TR = R T R^T, accumulated in one pass over the two contractions.
      DO I = 1, 3
        DO J = 1, 3
          TR(I,J) = 0.0D0
          DO K = 1, 3
            DO L = 1, 3
              TR(I,J) = TR(I,J) + R(I,K)*T(K,L)*R(J,L)
            END DO
          END DO
        END DO
      END DO
C     Back to Voigt, undoing the storage convention applied above.
      DO I = 1, NDI
        OUTPUT(I) = TR(I,I)
      END DO
      IF (NSHR .GE. 1) OUTPUT(NDI+1) = TR(1,2)/HALFSH
      IF (NSHR .GE. 2) OUTPUT(NDI+2) = TR(1,3)/HALFSH
      IF (NSHR .GE. 3) OUTPUT(NDI+3) = TR(2,3)/HALFSH
      RETURN
      END
"""

#: ``CALL SPRIND(S, PS, AN, LSTR, NDI, NSHR)`` -- principal values and directions.
SPRIND_DEFINITION = """
      SUBROUTINE SPRIND(S, PS, AN, LSTR, NDI, NSHR)
C     Abaqus utility: principal values PS(1..3), ascending, and AN(K,1..3),
C     the direction cosines of the principal direction of PS(K), of a
C     symmetric tensor in Voigt storage (NDI direct, then shears 12,13,23;
C     LSTR=2 means the stored shears are engineering shears). Supplied
C     because the solver provides it at link time; the eigenproblem is
C     solved by the supplied DSPEVD, which averages a repeated cluster.
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION S(NDI+NSHR), PS(3), AN(3,3)
      DIMENSION T(3,3), AP(6), W(3), Z(3,3), WORK(28)
      INTEGER IWORK(18), INFO
      HALFSH = 1.0D0
      IF (LSTR .EQ. 2) HALFSH = 0.5D0
      DO I = 1, 3
        DO J = 1, 3
          T(I,J) = 0.0D0
        END DO
      END DO
      DO I = 1, NDI
        T(I,I) = S(I)
      END DO
      IF (NSHR .GE. 1) T(1,2) = S(NDI+1)*HALFSH
      IF (NSHR .GE. 2) T(1,3) = S(NDI+2)*HALFSH
      IF (NSHR .GE. 3) T(2,3) = S(NDI+3)*HALFSH
C     Packed upper triangle, column by column, as DSPEVD reads it.
      AP(1) = T(1,1)
      AP(2) = T(1,2)
      AP(3) = T(2,2)
      AP(4) = T(1,3)
      AP(5) = T(2,3)
      AP(6) = T(3,3)
      CALL DSPEVD('V', 'U', 3, AP, W, Z, 3, WORK, 28, IWORK, 18, INFO)
      DO K = 1, 3
        PS(K) = W(K)
        DO I = 1, 3
          AN(K,I) = Z(I,K)
        END DO
      END DO
      RETURN
      END
"""

#: ``CALL SPRINC(S, PS, LSTR, NDI, NSHR)`` -- principal values only.
SPRINC_DEFINITION = """
      SUBROUTINE SPRINC(S, PS, LSTR, NDI, NSHR)
C     Abaqus utility: principal values PS(1..3), ascending, of a symmetric
C     tensor in Voigt storage. The values SPRIND returns, directions dropped.
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION S(NDI+NSHR), PS(3), AN(3,3)
      CALL SPRIND(S, PS, AN, LSTR, NDI, NSHR)
      RETURN
      END
"""

#: ``CALL SINV(STRESS, SINV1, SINV2, NDI, NSHR)`` -- mean stress and Mises stress.
SINV_DEFINITION = """
      SUBROUTINE SINV(STRESS, SINV1, SINV2, NDI, NSHR)
C     Abaqus utility: SINV1 = tr(sigma)/3 and SINV2 = sqrt(3/2 s:s), s the
C     deviator, for a stress-type tensor in Voigt storage. At s = 0 the
C     Mises stress has a kink; it is returned as zero with zero derivative.
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NDI+NSHR), D(3)
      SINV1 = 0.0D0
      DO I = 1, NDI
        SINV1 = SINV1 + STRESS(I)
      END DO
      SINV1 = SINV1/3.0D0
      DO I = 1, 3
        D(I) = -SINV1
      END DO
      DO I = 1, NDI
        D(I) = STRESS(I) - SINV1
      END DO
      SQ = D(1)*D(1) + D(2)*D(2) + D(3)*D(3)
      DO I = NDI+1, NDI+NSHR
        SQ = SQ + 2.0D0*STRESS(I)*STRESS(I)
      END DO
      SQ = 1.5D0*SQ
      IF (SQ .GT. 0.0D0) THEN
        SINV2 = SQRT(SQ)
      ELSE
        SINV2 = 0.0D0
      END IF
      RETURN
      END
"""

#: ``CALL DGESV(N, NRHS, A, LDA, IPIV, B, LDB, INFO)`` -- the LAPACK driver
#: written over the supplied DGETRF/DGETRS: same arguments, same INFO meaning.
DGESV_DEFINITION = """
      SUBROUTINE DGESV(N, NRHS, A, LDA, IPIV, B, LDB, INFO)
      IMPLICIT NONE
      INTEGER N, NRHS, LDA, LDB, IPIV(*), INFO
      DOUBLE PRECISION A(LDA,*), B(LDB,*)
      INFO = 0
      IF (N.LT.0) THEN
        INFO = -1
      ELSE IF (NRHS.LT.0) THEN
        INFO = -2
      ELSE IF (LDA.LT.MAX(1,N)) THEN
        INFO = -4
      ELSE IF (LDB.LT.MAX(1,N)) THEN
        INFO = -7
      END IF
      IF (INFO.NE.0) RETURN
      CALL DGETRF(N, N, A, LDA, IPIV, INFO)
      IF (INFO.EQ.0) THEN
        CALL DGETRS('N', N, NRHS, A, LDA, IPIV, B, LDB, INFO)
      END IF
      END
"""

#: ``CALL DGETRI(N, A, LDA, IPIV, WORK, LWORK, INFO)`` -- inverse from the
#: factors DGETRF left in A, by solving A X = I with the supplied DGETRS.
DGETRI_DEFINITION = """
      SUBROUTINE DGETRI(N, A, LDA, IPIV, WORK, LWORK, INFO)
      IMPLICIT NONE
      INTEGER N, LDA, LWORK, IPIV(*), INFO
      INTEGER ROW, COL
      DOUBLE PRECISION A(LDA,*), WORK(*)
      DOUBLE PRECISION X(MAX(1,N),MAX(1,N))
      INFO = 0
      IF (N.LT.0) THEN
        INFO = -1
      ELSE IF (LDA.LT.MAX(1,N)) THEN
        INFO = -3
      ELSE IF (LWORK.LT.MAX(1,N) .AND. LWORK.NE.-1) THEN
        INFO = -6
      END IF
      IF (INFO.NE.0) RETURN
      WORK(1) = DBLE(MAX(1,N))
      IF (LWORK.EQ.-1 .OR. N.EQ.0) RETURN
      DO ROW = 1,N
        IF (A(ROW,ROW).EQ.0.0D0) THEN
          INFO = ROW
          RETURN
        END IF
      END DO
      DO COL = 1,N
        DO ROW = 1,N
          X(ROW,COL) = 0.0D0
        END DO
        X(COL,COL) = 1.0D0
      END DO
      CALL DGETRS('N', N, N, A, LDA, IPIV, X, N, INFO)
      IF (INFO.NE.0) RETURN
      DO COL = 1,N
        DO ROW = 1,N
          A(ROW,COL) = X(ROW,COL)
        END DO
      END DO
      END
"""

#: Keyed on the name the CALL uses, upper case.
UTILITY_DEFINITIONS: dict[str, str] = {
    "ROTSIG": ROTSIG_DEFINITION,
    "DSPEVD": DSPEVD_DEFINITION,
    "DGETRF": DGETRF_DEFINITION,
    "DGETRS": DGETRS_DEFINITION,
    "DGESV": DGESV_DEFINITION,
    "DGETRI": DGETRI_DEFINITION,
    "SPRIND": SPRIND_DEFINITION,
    "SPRINC": SPRINC_DEFINITION,
    "SINV": SINV_DEFINITION,
}

#: What a supplied body itself calls, so supplying it supplies these too.
UTILITY_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "SPRINC": ("SPRIND",),
    "SPRIND": ("DSPEVD",),
    "DGESV": ("DGETRF", "DGETRS"),
    "DGETRI": ("DGETRS",),
}

#: Supplied bodies of routines the SOLVER links in. The transform uses their
#: lifted copies; the emitted file must not also define the real routine,
#: which would replace the solver's own for every other caller in the job.
SOLVER_UTILITIES = frozenset({"ROTSIG", "SPRINC", "SPRIND", "SINV"})


def available_definitions(names) -> tuple[str, ...]:
    """Which of ``names`` this module can supply a definition for, with what
    those definitions call in turn."""
    wanted = {str(name).strip().upper() for name in names if str(name).strip()}
    found = wanted & set(UTILITY_DEFINITIONS)
    pending = list(found)
    while pending:
        for dependency in UTILITY_DEPENDENCIES.get(pending.pop(), ()):
            if dependency not in found:
                found.add(dependency)
                pending.append(dependency)
    return tuple(sorted(found))


def definition_text(names) -> str:
    """The Fortran for every supplied name, in a stable order.

    Empty when nothing is supplied, so a caller can append unconditionally
    without changing a source that needed no help.
    """
    return "".join(UTILITY_DEFINITIONS[name] for name in available_definitions(names))


def supply_reachable_definitions(parsed, roots):
    """Append missing built-ins reached from roots, preserving supplied sources."""
    from umat_oti.core.model import ParsedFortranSource
    from umat_oti.fortran.parser import logical_lines_from_text, parse_subroutines
    from umat_oti.transform.helper_lifting import _routine_callees, function_names, routines_by_name

    routines = routines_by_name(parsed)
    functions = function_names(parsed)
    source_lines = parsed.text.splitlines()
    pending = [str(name).upper() for name in roots]
    visited, supplied = set(), set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        if name in routines:
            pending.extend(_routine_callees(routines[name], parsed.form, source_lines, function_names=functions))
        elif name in UTILITY_DEFINITIONS:
            supplied.add(name)
    supplied = set(available_definitions(supplied))
    # A body is supplied only for a name the source does not define itself.
    supplied -= set(routines)
    if not supplied:
        return parsed, ()
    # No statement labels anywhere in these bodies: the free-form conversion
    # below goes through fixed-form logical lines, which drop columns 1-5.
    addition = "".join(UTILITY_DEFINITIONS[name] for name in sorted(supplied))
    if parsed.form == "free":
        addition = "\n".join(line.text for line in logical_lines_from_text(addition, "fixed")) + "\n"
    text = parsed.text.rstrip("\n") + "\n" + addition
    lines = logical_lines_from_text(text, parsed.form)
    return ParsedFortranSource(parsed.path, parsed.form, text, lines, parse_subroutines(lines)), tuple(sorted(supplied))


def strip_supplied_solver_bodies(text: str, supplied) -> str:
    """``text`` without the REAL bodies of supplied solver utilities.

    The supplied body is appended to the source so the lifter can make its
    OTI copy (``SPRINC_OTI``). Left in the emitted file it would also define
    the real ``SPRINC`` in the user-subroutine object, and that definition
    would replace the solver's own for every other caller in the job. The
    emitted file keeps calling the solver's routine wherever it calls the real
    one, and the lifted copy wherever it calls ``*_OTI``. Only the LAST
    definition of each name is removed -- the appended one -- so an author's
    own routine of the same name, which the transform never supplies over,
    could not be touched even if it existed.
    """
    import re

    names = sorted(set(str(n).upper() for n in supplied) & SOLVER_UTILITIES)
    if not names:
        return text
    lines = text.splitlines(keepends=True)
    for name in names:
        header = re.compile(rf"^\s*SUBROUTINE\s+{name}\s*\(", re.IGNORECASE)
        starts = [i for i, line in enumerate(lines) if header.match(line)]
        if not starts:
            continue
        start = starts[-1]
        end = start
        while end < len(lines) and not re.match(r"^\s*END\s*(?:SUBROUTINE\b.*)?$", lines[end],
                                                   re.IGNORECASE):
            end += 1
        if end >= len(lines):
            continue
        # "!" in column 1 is a comment in both source forms.
        note = (f"! {name}: supplied body removed from the emitted file; the solver "
                f"provides the real routine and the transform calls {name}_OTI.\n")
        lines[start:end + 1] = [note]
    return "".join(lines)
