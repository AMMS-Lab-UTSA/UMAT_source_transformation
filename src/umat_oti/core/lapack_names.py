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

#: The ones that are FUNCTIONS, referenced in expressions rather than CALLed.
LAPACK_BLAS_FUNCTIONS = frozenset("""
DDOT DSDOT DNRM2 DASUM IDAMAX DLAMCH DLAPY2 DLANGE DLANSY
""".split())


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


#: Routines whose results in MKL (the library Abaqus links) and in reference
#: BLAS differ for some arguments, not only in rounding: DNRM2 and DSCAL with
#: INCX <= 0 (reference BLAS returns zero / does nothing, MKL computes).
MKL_SEMANTICS = frozenset({"DNRM2", "DSCAL"})


def needs_mkl_or_twins(text: str) -> tuple:
    """Why a stand-alone build of ``text`` must link MKL or the twins rather than
    another LAPACK/BLAS: the standard names it defines itself (another library's
    routines would call them), and the routines it references whose semantics
    differ between MKL and reference BLAS. Empty when any library will do."""
    import re

    reasons = [f"the source defines {name} itself" for name in standard_names_defined_in(text)]
    for name in sorted(MKL_SEMANTICS):
        if re.search(rf"(?im)^[^cC*!\n][^!\n]*(?<![A-Za-z0-9_]){name}\s*\(", text):
            reasons.append(f"the source calls {name}, whose result for INCX <= 0 differs between "
                           f"MKL and reference BLAS")
    return tuple(reasons)
