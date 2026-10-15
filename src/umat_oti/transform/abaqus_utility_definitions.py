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

Licence: DGESV (dgesv.f) and DGETRI's interface and argument checks (dgetri.f)
follow Reference LAPACK, as do the bodies imported from lu_definitions and
blas_definitions; Reference LAPACK/BLAS is BSD-3-Clause, Copyright (c)
1992-2023 The University of Tennessee and The University of Tennessee Research
Foundation, (c) 2000-2023 The University of California Berkeley, (c) 2006-2023
The University of Colorado Denver. The full notice is
:data:`REFERENCE_LAPACK_LICENCE` (and THIRD_PARTY_NOTICES.md, section 5);
:func:`library_licence_comment` puts it at the top of every generated file that
holds one of these bodies.
"""
from __future__ import annotations

from umat_oti.transform.spectral_definitions import DSPEVD_DEFINITION
from umat_oti.transform.lu_definitions import DGETRF_DEFINITION, DGETRS_DEFINITION
from umat_oti.transform.blas_definitions import (
    DAXPY_DEFINITION, DCOPY_DEFINITION, DDOT_DEFINITION, DGEMM_DEFINITION, DGEMV_DEFINITION,
    DNRM2_DEFINITION, DSCAL_DEFINITION, DSYEV_DEFINITION)

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
    "DSYEV": DSYEV_DEFINITION,
    "DGEMM": DGEMM_DEFINITION,
    "DGEMV": DGEMV_DEFINITION,
    "DCOPY": DCOPY_DEFINITION,
    "DSCAL": DSCAL_DEFINITION,
    "DAXPY": DAXPY_DEFINITION,
    "DDOT": DDOT_DEFINITION,
    "DNRM2": DNRM2_DEFINITION,
}

#: The supplied library routines that are FUNCTIONS: a UMAT references them in
#: expressions, not with CALL (see :func:`with_supplied_library_functions`).
LIBRARY_FUNCTIONS = ("DDOT", "DNRM2")

#: What a supplied body itself calls, so supplying it supplies these too.
UTILITY_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "SPRINC": ("SPRIND",),
    "SPRIND": ("DSPEVD",),
    "DGESV": ("DGETRF", "DGETRS"),
    "DGETRI": ("DGETRS",),
    "DSYEV": ("DSPEVD",),
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


#: Library routines Abaqus links into a user subroutine (its LAPACK) whose
#: bodies are supplied above: everything supplied except the solver utilities.
LIBRARY_ROUTINES = tuple(sorted(set(UTILITY_DEFINITIONS) - SOLVER_UTILITIES))


#: The private name of a library routine's real twin wherever one is compiled
#: into an object that also holds an author's code: never a standard LAPACK or
#: BLAS name, which would replace the host library's routine for every caller
#: in the process (see docs/PROVIDER.md, "Library routines").
PRIVATE_REAL_FORMAT = "UMATOTI_{name}_R"
#: The private name of the OTI copy the transform calls.
PRIVATE_OTI_FORMAT = "UMATOTI_{name}_OTI"
#: The private name of a supplied body that a supplied routine calls when the
#: author defines a routine of the same name (its OTI copy is then
#: ``PRIVATE_OTI_FORMAT`` already).
PRIVATE_SUPPLIED_FORMAT = "UMATOTI_{name}"


#: The licence of Reference LAPACK/BLAS, which the library bodies follow
#: (lu_definitions, blas_definitions, DGESV and DGETRI above); see
#: THIRD_PARTY_NOTICES.md, section 5. Kept with every file the transform or the
#: provider writes that holds one of those bodies.
REFERENCE_LAPACK_LICENCE = """\
Copyright (c) 1992-2023 The University of Tennessee and The University
                        of Tennessee Research Foundation.  All rights
                        reserved.
Copyright (c) 2000-2023 The University of California Berkeley. All
                        rights reserved.
Copyright (c) 2006-2023 The University of Colorado Denver.  All rights
                        reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

- Redistributions of source code must retain the above copyright
  notice, this list of conditions and the following disclaimer.

- Redistributions in binary form must reproduce the above copyright
  notice, this list of conditions and the following disclaimer listed
  in this license in the documentation and/or other materials
  provided with the distribution.

- Neither the name of the copyright holders nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

The copyright holders provide no reassurances that the source code
provided does not infringe any patent, copyright, or any other
intellectual property rights of third parties.  The copyright holders
disclaim any liability to any recipient for claims brought against
recipient by any third party for infringement of that parties
intellectual property rights.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""


def library_licence_comment(names, comment: str = "!") -> str:
    """The comment block a generated file holding bodies of the library routines
    ``names`` (DGESV, DGEMM, ...) starts with: what follows Reference LAPACK/BLAS,
    and its licence. Empty when ``names`` holds none of them."""
    held = sorted({str(name).upper().replace("UMATOTI_", "", 1) for name in names}
                  & set(LIBRARY_ROUTINES) - {"DSPEVD"})
    if not held:
        return ""
    lines = [f"The bodies of {', '.join(held)} in this file (under private names) follow",
             "Reference LAPACK/BLAS, from which their algorithms and loop orders are derived;",
             "see THIRD_PARTY_NOTICES.md, section 5, of umat-oti. Licence of Reference LAPACK/BLAS:",
             "", *REFERENCE_LAPACK_LICENCE.splitlines()]
    return "".join(f"{comment} {line}".rstrip() + "\n" for line in lines) + "\n"


#: The private name an AUTHOR's own definition of a standard LAPACK/BLAS name
#: gets in everything generated from the source (the transformed file, its
#: helpers, the provider's objects), with every reference to it.
PRIVATE_AUTHOR_FORMAT = "UMATOTI_AUTH_{name}"


def author_library_definitions(parsed) -> dict[str, str]:
    """``{NAME: private name}`` for every standard LAPACK/BLAS name (DGETRF) the
    source defines itself, as a subroutine or a function."""
    from umat_oti.core.lapack_names import STANDARD_LAPACK_BLAS
    from umat_oti.transform.helper_lifting import routines_by_name

    return {name: PRIVATE_AUTHOR_FORMAT.format(name=name)
            for name in sorted(set(routines_by_name(parsed)) & STANDARD_LAPACK_BLAS)}


def renamed_names_in_code(text: str, renames: dict, form: str) -> str:
    """``text`` with each name in ``renames`` replaced as a whole word in the
    code: comment lines, trailing ``!`` comments and character constants are left
    as they are. Lines are not split, so line numbers are kept."""
    import re

    if not renames:
        return text
    pattern = re.compile(r"(?<![A-Za-z0-9_$%])(" + "|".join(sorted(map(re.escape, renames), key=len,
                                                               reverse=True))
                         + r")(?![A-Za-z0-9_$])", re.IGNORECASE)

    def code(segment: str) -> str:
        return pattern.sub(lambda m: renames[m.group(1).upper()], segment)

    out = []
    for line in text.splitlines(keepends=True):
        if form == "fixed" and line[:1] in "cC*!":
            out.append(line)
            continue
        if line.lstrip().startswith("!"):
            out.append(line)
            continue
        head, body = (line[:6], line[6:]) if form == "fixed" else ("", line)
        pieces, start, quote, index = [head], 0, "", 0
        while index < len(body):
            char = body[index]
            if quote:
                if char == quote:
                    if body[index + 1:index + 2] == quote:
                        index += 1
                    else:
                        pieces.append(body[start:index + 1])
                        start, quote = index + 1, ""
            elif char in "'\"":
                pieces.append(code(body[start:index]))
                start, quote = index, char
            elif char == "!":
                break
            index += 1
        if quote:
            pieces.append(body[start:])
        else:
            pieces.append(code(body[start:index]) + body[index:])
        out.append("".join(pieces))
    return "".join(out)


def rename_author_library_definitions(text: str, renames: dict, form: str) -> str:
    """``text`` (a file the transform writes) with the author's own definitions of
    standard LAPACK/BLAS names, their lifted copies and every reference to them
    renamed: DGETRF -> UMATOTI_AUTH_DGETRF, DGETRF_OTI -> UMATOTI_AUTH_DGETRF_OTI.

    Left under its standard name, the author's DGETRF would be exported by the
    user-subroutine object and, in Abaqus, replace the solver's dgetrf_ for
    every caller in the process (see :func:`strip_supplied_solver_bodies`).
    The rename is applied to the written text only, after the transform and its
    checks: up to then the routine is an ordinary helper of the author's,
    promoted, lifted and checked like one. The author's own calls keep reaching
    the author's routine. A library routine the author calls and does not
    define keeps its whole library chain: Abaqus's MKL runs its own LU inside
    DGESV, whatever DGETRF a user library defines (measured: an author DGETRF
    linked beside MKL's DGESV is not called; beside reference LAPACK 3.9.0 it
    is), so the supplied DGESV calls a supplied DGETRF under a private name
    (:func:`supply_reachable_definitions`), never the author's.
    """
    if not renames:
        return text
    mapping = {}
    for name, private in renames.items():
        mapping[name.upper()] = private
        mapping[f"{name.upper()}_OTI"] = f"{private}_OTI"
    return renamed_names_in_code(text, mapping, form)


def renamed_library_calls(text: str, names, name_format: str) -> str:
    """``text`` with every SUBROUTINE definition of and CALL to the routines in
    ``names`` renamed by ``name_format`` (e.g. DGESV -> UMATOTI_DGESV_R)."""
    import re

    for name in names:
        new = name_format.format(name=name)
        if name in LIBRARY_FUNCTIONS:
            # A function's name is also its result variable and appears in
            # expressions: every occurrence is renamed.
            text = re.sub(rf"(?i)(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])", new, text)
            continue
        text = re.sub(rf"(?i)\b(SUBROUTINE|CALL|EXTERNAL)(\s+){name}\b(?=\s*(\(|$|,))",
                      lambda m: m.group(1) + m.group(2) + new, text)
        text = re.sub(rf"(?i)(\bEND\s+SUBROUTINE\s+){name}\b", lambda m: m.group(1) + new, text)
    return text


def privatise_oti_copies(text: str, supplied) -> str:
    """``text`` with the OTI copies of supplied LAPACK/BLAS routines (``DGESV_OTI``)
    renamed to their private names (``UMATOTI_DGESV_OTI``), definitions and calls
    alike. The Abaqus utilities keep ``ROTSIG_OTI`` and the like."""
    import re

    for name in sorted(set(str(n).upper() for n in supplied) & set(LIBRARY_ROUTINES)):
        text = re.sub(rf"(?i)(?<![A-Za-z0-9_]){name}_OTI\b", PRIVATE_OTI_FORMAT.format(name=name), text)
    return text


def library_twin_sources(name_format: str = "{name}") -> dict[str, str]:
    """The real bodies of :data:`LIBRARY_ROUTINES`, as free form, one routine
    per entry, so a caller can put each in its own archive member and let the
    linker take only what the original leaves undefined.

    A stand-alone build of an ORIGINAL that calls DGESV has no LAPACK to link,
    where Abaqus would supply one. These are the bodies the transform supplies
    to the transformed build, over plain reals, so the original's reference
    build and the transformed build pivot and round alike.

    Inside the bodies, a library routine always calls the private twins
    (``UMATOTI_DGETRF_R``), never a standard name: the chain stays whole
    even where the author defines a DGETRF of their own, as it does in MKL
    (see :func:`rename_author_library_definitions`).

    ``{NAME: body}`` with the entry points named by ``name_format``; unless
    that is :data:`PRIVATE_REAL_FORMAT`, the private chain the entry points
    call is included too, keyed by its private name.
    """
    import re

    from umat_oti.fortran.parser import logical_lines_from_text

    private = {name: renamed_library_calls(
        _without_dble("\n".join(line.text for line in
                                 logical_lines_from_text(UTILITY_DEFINITIONS[name], "fixed")) + "\n"),
        LIBRARY_ROUTINES, PRIVATE_REAL_FORMAT) for name in LIBRARY_ROUTINES}
    if name_format == PRIVATE_REAL_FORMAT:
        return private
    entries = {}
    for name, text in private.items():
        own = PRIVATE_REAL_FORMAT.format(name=name)
        entry = name_format.format(name=name)
        if name in LIBRARY_FUNCTIONS:
            entries[name] = re.sub(rf"(?i)(?<![A-Za-z0-9_]){own}(?![A-Za-z0-9_])", entry, text)
            continue
        text = re.sub(rf"(?i)\b(SUBROUTINE\s+){own}\b", lambda m: m.group(1) + entry, text, count=1)
        entries[name] = re.sub(rf"(?i)(\bEND\s+SUBROUTINE\s+){own}\b", lambda m: m.group(1) + entry, text)
    return {**entries, **{PRIVATE_REAL_FORMAT.format(name=name): text for name, text in private.items()}}


def _without_dble(text: str) -> str:
    """``DBLE(n)`` written ``(1.0D0*(n))``: the same double for every integer
    argument these bodies give it, and a form a REAL(16) build of the stub block
    (which turns DOUBLE PRECISION into REAL*16 and DBLE into QEXT, an intrinsic
    gfortran does not have) still compiles."""
    import re

    out, position = [], 0
    for match in re.finditer(r"(?i)\bDBLE\s*\(", text):
        if match.start() < position:
            continue
        depth, index = 0, match.end() - 1
        while index < len(text):
            depth += {"(": 1, ")": -1}.get(text[index], 0)
            if depth == 0:
                break
            index += 1
        out.append(text[position:match.start()])
        out.append("(1.0D0*(" + _without_dble(text[match.end():index]) + "))")
        position = index + 1
    out.append(text[position:])
    return "".join(out)


#: The comment line that starts the library functions appended to a source
#: (:func:`with_supplied_library_functions`); it names them.
LIBRARY_FUNCTIONS_MARKER = "UMAT-OTI SUPPLIED LIBRARY FUNCTIONS:"


def _code_lines(text: str):
    for line in text.splitlines():
        if line[:1] in ("*", "!") or (line[:1] in ("c", "C") and line[1:2] in ("", " ", "\t", "-", "=", "*")):
            continue
        if line.lstrip().startswith("!"):
            continue
        yield line.split("!", 1)[0]


def library_function_references(text: str) -> tuple:
    """The standard LAPACK/BLAS FUNCTIONS (DDOT, DNRM2, DLAMCH, ...) ``text``
    references in an expression and neither defines nor declares as an array,
    sorted."""
    import re

    from umat_oti.core.lapack_names import LAPACK_BLAS_FUNCTIONS, standard_names_defined_in

    defined = set(standard_names_defined_in(text))
    code = list(_code_lines(text))
    found = set()
    for name in LAPACK_BLAS_FUNCTIONS - defined:
        reference = re.compile(rf"(?i)(?<![A-Za-z0-9_%]){name}\s*\(")
        array = re.compile(rf"(?i)^\s*(?:DIMENSION|REAL|DOUBLE\s*PRECISION|INTEGER|LOGICAL|COMMON)\b"
                           rf"[^=]*(?<![A-Za-z0-9_]){name}\s*\(")
        called = re.compile(rf"(?i)\bCALL\s+{name}\b")
        if any(array.match(line) for line in code):
            continue
        if any(reference.search(line) and not called.search(line) for line in code):
            found.add(name)
    return tuple(sorted(found))


def with_supplied_library_functions(text: str, form: str) -> tuple:
    """``(text, names)``: ``text`` with the bodies of the supplied library
    FUNCTIONS it references and does not define (DDOT, DNRM2) appended, after
    a marker comment that names them.

    A function is referenced in expressions, so nothing that reads the source
    could tell DNRM2(NTENS,B,1) from an element of an undeclared array: the
    analysis promoted it as an array with no shape. Read with the bodies
    appended, the reference is a call of a function the file defines, which
    the transform lifts like an author's own function; the transform then
    removes the real body from what it writes (the host's library provides it)
    and gives the lifted copy a private name (UMATOTI_DNRM2_OTI). Lines are only
    appended, so every line number of the source is unchanged. Idempotent: a
    text that already carries the marker is returned as it is.
    """
    import re

    marker = re.search(rf"{re.escape(LIBRARY_FUNCTIONS_MARKER)}([A-Z0-9 ]*)", text)
    if marker:
        return text, tuple(marker.group(1).split())
    names = tuple(name for name in library_function_references(text) if name in LIBRARY_FUNCTIONS)
    if not names:
        return text, ()
    from umat_oti.fortran.parser import logical_lines_from_text

    addition = "".join(UTILITY_DEFINITIONS[name] for name in names)
    comment = "C     " if form == "fixed" else "! "
    if form != "fixed":
        addition = "\n".join(line.text for line in logical_lines_from_text(addition, "fixed")) + "\n"
    return (text.rstrip("\n") + "\n" + f"{comment}{LIBRARY_FUNCTIONS_MARKER} {' '.join(names)}\n"
            + addition), names


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
    needed = set(available_definitions(supplied))
    # A body is supplied under its own name only for a name the source does not
    # define itself. A library routine's chain stays the library's, though: when
    # the author defines a routine a supplied body calls (their own DGETRF, under
    # a supplied DGESV), that body calls a supplied copy under a private name
    # (UMATOTI_DGETRF, lifted as UMATOTI_DGETRF_OTI), as MKL's DGESV runs its own
    # LU whatever DGETRF a user library defines.
    shadowed = sorted(needed & set(routines) & set(LIBRARY_ROUTINES))
    entries = sorted(needed - set(routines))
    if not entries:
        return parsed, ()
    bodies = [renamed_library_calls(UTILITY_DEFINITIONS[name], shadowed, PRIVATE_SUPPLIED_FORMAT)
              for name in entries + shadowed]
    supplied = entries + [PRIVATE_SUPPLIED_FORMAT.format(name=name) for name in shadowed]
    # No statement labels anywhere in these bodies: the free-form conversion
    # below goes through fixed-form logical lines, which drop columns 1-5.
    addition = "".join(bodies)
    if parsed.form == "free":
        addition = "\n".join(line.text for line in logical_lines_from_text(addition, "fixed")) + "\n"
    text = parsed.text.rstrip("\n") + "\n" + addition
    lines = logical_lines_from_text(text, parsed.form)
    return ParsedFortranSource(parsed.path, parsed.form, text, lines, parse_subroutines(lines)), tuple(supplied)


def strip_supplied_solver_bodies(text: str, supplied, form: str = "free") -> str:
    """``text`` without the REAL bodies of the supplied routines: solver
    utilities and LAPACK/BLAS routines alike.

    Measured on Abaqus 2021: the user-subroutine library (libstandardU.so) is a
    DT_NEEDED of libABQSMAStaCore.so and sits at position 31 of the solver's
    global symbol scope, MKL (libmkl_rt.so) at 66; the solver's own
    libABQSMABlaModule.so imports dgesv_, dgetrf_, dgetrs_, dgemm_, dgemv_,
    dsyev_ and dpotrf_. A dgesv_ defined in the user library would therefore
    be the one every caller in the process gets.

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

    privates = {PRIVATE_SUPPLIED_FORMAT.format(name=name) for name in LIBRARY_ROUTINES}
    names = sorted(set(str(n).upper() for n in supplied) & (set(UTILITY_DEFINITIONS) | privates))
    if not names:
        return text
    lines = text.splitlines(keepends=True)
    for name in names:
        header = re.compile(rf"^\s*(?:(?:DOUBLE\s*PRECISION|REAL\s*\*\s*8|INTEGER)\s+)?"
                            rf"(?:SUBROUTINE|FUNCTION)\s+{name}\s*\(", re.IGNORECASE)
        starts = [i for i, line in enumerate(lines) if header.match(line)]
        if not starts:
            continue
        start = starts[-1]
        end = start
        while end < len(lines) and not re.match(r"^\s*END\s*(?:(?:SUBROUTINE|FUNCTION)\b.*)?$",
                                                   lines[end], re.IGNORECASE):
            end += 1
        if end >= len(lines):
            continue
        # A fixed-form file needs its comment marker in column 1 AND nothing in
        # column 6 that a fixed-to-free conversion could take for a continuation.
        marker = "C     " if form == "fixed" else "! "
        copy = PRIVATE_OTI_FORMAT.format(name=name) if name in LIBRARY_ROUTINES else f"{name}_OTI"
        if name.startswith("UMATOTI_"):
            note = (f"{marker}{name}: supplied body (the library's own, for the supplied routines "
                    f"that call it) removed from the emitted file; the transform calls its OTI "
                    f"copy {copy}.\n")
        else:
            note = (f"{marker}{name}: supplied body removed from the emitted file; the host "
                    f"(Abaqus, its MKL for LAPACK/BLAS) provides the real routine, and the "
                    f"transform calls its OTI copy {copy}.\n")
        lines[start:end + 1] = [note]
    return "".join(lines)
