"""Names of the LAPACK and BLAS routines a UMAT may call.

Used to tell a call to a library routine apart from a call to a helper the
author forgot to supply, so that a routine umat-oti cannot differentiate is
refused by its name at transform time instead of failing to link later, and to
check that no generated object defines one of these names (a definition would
replace the host library's routine for every caller in the process).
Double precision only: a UMAT works in REAL*8.
"""

#: BLAS level 1, 2 and 3 (double precision).
BLAS = frozenset("""
DROTG DROTMG DROT DROTM DSWAP DSCAL DCOPY DAXPY DDOT DSDOT DNRM2 DASUM IDAMAX
DGEMV DGBMV DSYMV DSBMV DSPMV DTRMV DTBMV DTPMV DTRSV DTBSV DTPSV DGER DSYR DSPR DSYR2 DSPR2
DGEMM DSYMM DSYRK DSYR2K DTRMM DTRSM
""".split())

#: LAPACK drivers, computational and frequently called auxiliary routines (double precision).
LAPACK = frozenset("""
DGESV DGESVX DGETRF DGETF2 DGETRF2 DGETRS DGETRI DGECON DGEEQU DGERFS DGBSV DGBTRF DGBTRS DGTSV
DPOSV DPOTRF DPOTF2 DPOTRS DPOTRI DPOCON DPPSV DPPTRF DPPTRS DSYSV DSYTRF DSYTRS DSYTRI DSPSV
DGELS DGELSD DGELSS DGELSY DGEQRF DGEQP3 DORGQR DORMQR DGERQF DGELQF DORGLQ
DGESVD DGESDD DGEEV DGEEVX DGEES DGEBAL DGEHRD DHSEQR DGGEV
DSYEV DSYEVD DSYEVR DSYEVX DSPEV DSPEVD DSPEVX DSBEV DSTEV DSTEQR DSTERF DSYTRD DORGTR
DLACPY DLASET DLANGE DLANSY DLAMCH DLAPY2 DLASWP DLASCL DTRTRI DTRTRS DTRCON
""".split())

STANDARD_LAPACK_BLAS = BLAS | LAPACK


def standard_names_defined_in(text: str) -> tuple:
    """The standard LAPACK/BLAS names ``text`` defines as a SUBROUTINE or FUNCTION
    (an author's own DGETRF), sorted. A line-level read of the source, enough to
    choose how a stand-alone build links; the transform itself reads the parse."""
    import re

    header = re.compile(r"(?i)^\s*(?:\d+\s+)?(?:(?:RECURSIVE|PURE|ELEMENTAL|DOUBLE\s*PRECISION|"
                        r"REAL(?:\s*\*\s*\d+)?|INTEGER(?:\s*\*\s*\d+)?|LOGICAL)\s+)*"
                        r"(?:SUBROUTINE|FUNCTION)\s+([A-Z][A-Z0-9_]*)")
    found = set()
    for line in text.splitlines():
        if line[:1] in ("*", "!") or (line[:1] in ("c", "C") and line[1:2] in ("", " ", "\t", "-", "=", "*")):
            continue
        match = header.match(line)
        if match and match.group(1).upper() in STANDARD_LAPACK_BLAS:
            found.add(match.group(1).upper())
    return tuple(sorted(found))
