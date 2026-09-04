# What the offline gate's disagreeing rows are, and what they are not

The offline stress-parity gate builds an original UMAT and its transform as
two standalone drivers, runs both from one declared starting state, and
compares the stress. At the time of writing, of 251 stored transforms it
decides 155: **123 agree** and **32 disagree**, at a relative tolerance of
1e-10. The worst difference among agreeing rows is 1.958e-11.

This note records what has been established about those 32, and — at least
as usefully — which explanations have been tested and refused. Every claim
here names the measurement behind it. Where a measurement could not be
trusted, that is said instead of a conclusion.

## The 32 split into two populations, not one

Dumping the stress arrays component by component separates them cleanly:

| | rows | signature |
|---|---|---|
| structural | 1 | a flipped sign, and a shear component where the original returns exactly zero |
| smooth | 31 | identical signs, identical zero pattern, differences spread from 1.5e-09 to 7.4e-03 |

They are almost entirely one family of sources (Jeff97 growth and shell
models). A single population of 32 would suggest one cause; two populations
of 31 and 1 do not.

## The structural row is a model at a bifurcation

`Wrinkle/l1-is-1--l2-is-11.for` disagrees by 1.10e+00 — the transform returns
`[+1.542e7, +1.542e7, +1.533e7, 2.009e5, 0, 0]` where the original returns
`[-1.486e6, -1.486e6, -1.483e6, 0, 0, 0]`: opposite sign, ten times the
magnitude, and a shear the original leaves at zero.

Its sibling `l1-is-1--l2-is-101.for` disagrees by 1.05e-04. `diff` between
the two files is **one line**:

```
61c61
<         Lambda2=1.1
---
>         Lambda2=1.01
```

The same code, one growth stretch changed, and four orders of magnitude
between the two disagreements. These are *wrinkling* models: they describe a
plate that buckles. Near the wrinkling threshold the mapping from input to
stress is by construction arbitrarily sensitive, and `Lambda2=1.1` sits
further past it than `Lambda2=1.01`.

That does not prove the row is not a defect. It does mean the row cannot
distinguish a defect from a branch flip, and any claim about it needs a
measurement that does.

## Refuted: floating-point reassociation

A transform re-emits arithmetic, and reassociating a sum of large cancelling
terms changes its last bits. If the sources were sensitive to that, a 1e-9
difference would be the floor rather than a finding.

Measured, on each source, by compiling **the author's own file** two ways that
are each a correct compilation of it, and comparing those two runs to each
other:

- `-O0 -ffp-contract=off` — evaluated as written
- `-O2 -ffp-contract=fast` — fused and reassociated

**The floor is 0.00e+00 on every one of the 32.** The runs are bit-identical.
These sources are not sensitive to reassociation, so the observed differences
are not reassociation noise. The hypothesis is dead, and the differences are
real.

## Refuted: literal precision widening

The transform appends `D0` to default-precision real literals on lines
carrying an OTI name, which does not widen storage but re-parses the literal:
`3.14159265359` and `3.14159265359D0` are 2.78e-08 apart, the right order of
magnitude for the smooth band.

Measured by removing the `D0` suffixes from a stored transform and rebuilding:
the disagreement was **identical to four figures**. The mechanism does not
account for the difference.

## Not established: the original's own single precision

Twenty-six of the disagreeing sources declare `REAL Lambda1, Lambda2, TotalT`
with no kind and carry **no** double-precision declaration anywhere — no
`REAL*8`, no `DOUBLE PRECISION`, no `IMPLICIT REAL*8`. In Fortran that means
those names, and every implicitly typed name under the default `A-H,O-Z`
rule, are 24-bit. The transform's `ONUMM6N1` components are 64-bit. Single
precision has a relative epsilon of about 1e-7, which sits in the middle of
the observed band.

This has **not** been established, and it is recorded here as an open
question rather than an answer. Two attempts to test it — rebuilding the
original with `-fdefault-real-8`, which promotes exactly the reals the author
left kindless — produced a standalone harness whose numbers disagreed with
the gate's by up to five orders of magnitude on the same source and the same
deck (1.9e-02 against the gate's 7.6e-08). A harness that cannot reproduce
the measurement it is trying to explain cannot refute or confirm anything,
so both runs were discarded rather than reported.

Testing it properly means instrumenting the gate itself rather than
reproducing it, so that the starting state, the probe and the material vector
are the gate's own by construction.

## What follows from this

- The 32 rows are **not** dismissible as numerical noise. That was tested and
  is false.
- They are **not** one phenomenon. One row is structural; 31 are smooth.
- The largest disagreement is in a model whose own sibling, differing by one
  constant, behaves four orders of magnitude better — so that row is evidence
  about conditioning at least as much as about the transform.
- No mechanism has been established for the smooth band, and none is claimed.

Nothing here changes a tolerance. A tolerance is what the gate asks of a
comparison; this note is about what the comparison is measuring.
