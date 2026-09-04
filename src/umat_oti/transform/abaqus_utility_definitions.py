"""Reference Fortran for the Abaqus utilities the solver provides, not the author.

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

What is deliberately NOT here: SPRIND and SPRINC. Those return principal values
and directions, which is an eigenproblem. Its derivative is not the derivative
of the algebra that computes it once eigenvalues coincide, so a body written
here would produce a tangent that is wrong exactly where a model is most likely
to be doing something interesting. Those sources keep their refusal until the
degenerate case is handled deliberately.
"""
from __future__ import annotations

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
      DO 20 I = 1, 3
        DO 10 J = 1, 3
          T(I,J) = 0.0D0
   10   CONTINUE
   20 CONTINUE
      DO 30 I = 1, NDI
        T(I,I) = S(I)
   30 CONTINUE
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
      DO 70 I = 1, 3
        DO 60 J = 1, 3
          TR(I,J) = 0.0D0
          DO 50 K = 1, 3
            DO 40 L = 1, 3
              TR(I,J) = TR(I,J) + R(I,K)*T(K,L)*R(J,L)
   40       CONTINUE
   50     CONTINUE
   60   CONTINUE
   70 CONTINUE
C     Back to Voigt, undoing the storage convention applied above.
      DO 80 I = 1, NDI
        OUTPUT(I) = TR(I,I)
   80 CONTINUE
      IF (NSHR .GE. 1) OUTPUT(NDI+1) = TR(1,2)/HALFSH
      IF (NSHR .GE. 2) OUTPUT(NDI+2) = TR(1,3)/HALFSH
      IF (NSHR .GE. 3) OUTPUT(NDI+3) = TR(2,3)/HALFSH
      RETURN
      END
"""

#: Keyed on the name the CALL uses, upper case.
UTILITY_DEFINITIONS: dict[str, str] = {
    "ROTSIG": ROTSIG_DEFINITION,
}


def available_definitions(names) -> tuple[str, ...]:
    """Which of ``names`` this module can supply a definition for."""
    wanted = {str(name).strip().upper() for name in names if str(name).strip()}
    return tuple(sorted(wanted & set(UTILITY_DEFINITIONS)))


def definition_text(names) -> str:
    """The Fortran for every supplied name, in a stable order.

    Empty when nothing is supplied, so a caller can append unconditionally
    without changing a source that needed no help.
    """
    return "".join(UTILITY_DEFINITIONS[name] for name in available_definitions(names))
