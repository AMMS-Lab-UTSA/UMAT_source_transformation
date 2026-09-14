# DOUBLE COMPLEX on the stress path: not supported, and the reason

**Verdict: an internal limitation of this transform. Ours, not the source's.**

Nine corpus sources are refused with

> `A` is declared DOUBLE COMPLEX and is on the stress path. The OTI type is
> built over the reals, so there is no complex shadow to promote `A` to, and a
> real shadow would drop the imaginary part silently.

All nine are genuine UMATs. Nothing is missing from them, nothing about them is
malformed, and no companion file would make them transform. The transform
cannot do it. That sentence is the whole of the classification: this is not an
external blocker and must never be counted as one.

## The nine

| source | DOUBLE COMPLEX names | on the stress path | tangent-only |
|---|---|---|---|
| tengzhang48/CoupFE `neo_hookean_umat.for` | 98 | 67 | 0 |
| tengzhang48/CoupFE `ogden_umat.for` | 116 | 69 | 0 |
| tengzhang48/CoupFE `small_strain_j2.for` | 118 | 30 | 0 |
| tengzhang48/CoupFE `small_strain_viscoelastic.for` | 111 | 21 | 0 |
| tengzhang48/abaqus_ufl `template_umat.for` | 110 | 17 | 0 |
| tengzhang48/abaqus_ufl `neo_hookean_umat.for` | 103 | 72 | 0 |
| tengzhang48/abaqus_ufl `ogden_umat.for` | 117 | 86 | 0 |
| tengzhang48/abaqus_ufl `small_strain_j2.for` | 123 | 31 | 0 |
| tengzhang48/abaqus_ufl `small_strain_viscoelastic.for` | 117 | 23 | 0 |

Measured with the transform's own dependency walk. The last column is the one
that closes the easy escape: not one complex variable in any of the nine is
tangent-only, so there is no arrangement in which the seed goes round the
complex region and only the discarded tangent passes through it.

## What they are

All nine come from one lineage -- `abaqus_ufl`, and a regeneration of it by
`coupfe.codegen`. They are **complex-step differentiation** UMATs: the
constitutive law is evaluated in `DOUBLE COMPLEX`, a step of `i*CS_H` is added
to one component of the input, and the tangent is read off the imaginary part.

```fortran
      DOUBLE PRECISION, PARAMETER :: CS_H = 1.0d-10
      ...
      CALL real2complex33(F, Fz)
      Fz(k,l) = Fz(k,l) + DCMPLX(0.0d0, CS_H)
      CALL neohookean_stress_PK1(Fz, props, Pz)
      dPdF(i,j,k,l) = AIMAG(Pz(i,j)) / CS_H
```

So the complex type here is not a material quantity. It is a hand-rolled dual
number: a forward-mode derivative carrier, doing by hand what this project does
with the OTI algebra. The primal stress is taken from the same complex routine
with a zero imaginary part (`P_real(i,j) = DBLE(Pz(i,j))`), which is why the
stress path runs through complex arithmetic and not only the tangent path.

## Why it cannot be done as it stands

The OTI algebra is generated over the reals. There is no complex constructor,
no complex assignment, and no mixed complex/OTI arithmetic. Compiled here, with
the module the transform itself emits:

```
$ gfortran -I. probe.f90 ... -o probe
probe.f90:9:8:
    9 |     x = z
      |        1
Error: Cannot convert COMPLEX(8) to TYPE(onumm6n1) at (1)
```

where `x` is `TYPE(ONUMM6N1)` and `z` is `DOUBLE COMPLEX`. That is the whole
obstruction, stated by the compiler: promoting one of these variables has no
target type to promote it to.

## The two ways it could be done, and what each would cost

1. **An OTI algebra over C.** Every operator in the generated module gains a
   complex overload and the type gains a complex part. That is a change to the
   OTI library and its generator, not to the transformer, and it doubles the
   arithmetic on every source in the corpus to serve nine.

2. **Recognise the complex-step idiom and delete it.** The rewrite is
   `DOUBLE COMPLEX -> TYPE(ONUMM..)`, `DCMPLX(x, 0)` -> `x`, `DBLE(z)` -> `z`,
   `AIMAG(z)` -> zero, and the `cs_dPdF` routine becomes the OTI extraction.
   It is sound **only** where every complex value on the stress path has an
   identically zero imaginary part, and that is a per-source semantic proof,
   not a type substitution: a source that genuinely computes with complex
   numbers -- a viscoelastic model in the frequency domain, say -- looks the
   same to a pattern matcher and would be silently wrecked by the same rewrite.

Neither is a small change and neither is on this project's critical path. The
refusal is correct, the reason is precise, and the nine stay refused.

## What must not happen

These nine must not be re-labelled `missing_external_dependency`,
`incomplete_or_corrupt_source` or anything else that puts the cause outside
this repository. Their refusal class is `genuine_umat`: the file is a real
UMAT and the transform is the part that cannot do it. Counting them as
external would raise a completion percentage by moving our own limitation onto
somebody else's file.
