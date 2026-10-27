# Replacement model R1: small-strain J2 plasticity with saturation (Voce) hardening and a local Newton solve

**Status: newly written, NOT transformed, NOT verified. No result from this model appears in the
manuscript.** Verification is a separate task with its own owner (`../../../missing-evidence.md`, task T4,
R1). Builder: Quill, 2026-10-27. Not reviewed.

## Why it exists
The V11 worked examples for parameter/state sensitivities (`m3_j2`, configuration B) and for the
internal constitutive Jacobian (`m5_cpflow`) belong to the twenty imported sweep models whose origin is
**unresolved** (open question Q12; manuscript Q-07; Restrepo comment C17; Curie B3; Vera B2). Under
publication-policy Clarification 2 they are moved out of the publishable text. This file is an
independently written model with documented provenance that can supply replacement evidence for:
- the **internal constitutive Jacobian** (it has a genuine scalar local Newton iteration, unlike the closed-form
  linear-hardening J2 example);
- **parameter and state sensitivities** along a prescribed strain path (six PROPS, one STATEV);
- a **consistent tangent through an iterative update** (Noether B3, Gauss I-3: the derivative of a loop that
  stops on a tolerance).

## Provenance (what is and is not claimed)
- Written from scratch on 2026-10-27 by Quill, an AI-assisted Council agent (Claude), from the standard
  formulation below as presented in de Souza Neto, Perić and Owen, *Computational Methods for Plasticity*
  (Wiley, 2008; key `desouzaneto2008`) and Simo and Hughes, *Computational Inelasticity* (Springer, 1998;
  key `simo1998`). Box and equation numbers in those books were **not** checked against a copy during
  writing, so none is cited; the equations below are the specification.
- No existing UMAT file was opened or copied: not the bundled `UMATs/` tree, not the imported sweep
  models, not the acquired corpus and not the Abaqus documentation example. Variable names were chosen
  independently.
- Not derived from restricted or collaborator material. Licence: none granted yet; Santiago decides. If it
  is added to the UMAT-OTI repository it falls under that repository's licence.
- The use of generative AI to write this file must be covered by the manuscript's generative-AI
  declaration (Q-43).

## Builder check performed (not verification)
Compiles without errors with GNU Fortran 16.1.0 (MinGW-w64, Windows): 
`gfortran -c -std=legacy -O1 -Wall -Wextra -Wline-truncation -I<dir with ABA_PARAM.INC> umat_j2_voce.f`,
with a stub `ABA_PARAM.INC` containing `IMPLICIT REAL*8(A-H,O-Z)`. Only "unused dummy argument"
warnings. All lines are at most 72 columns. **The routine has not been executed.**

## Specification (small strain, NLGEOM=NO, NTENS = 6)
Voigt order 11, 22, 33, 12, 13, 23; DSTRAN carries engineering shear strains γ = 2ε.
PROPS = (E, ν, σ_y0, H, Q, b); STATEV(1) = ε̄ᵖ (accumulated equivalent plastic strain).

- Elastic constants: G = E/(2(1+ν)), K = E/(3(1−2ν)), λ = K − 2G/3.
- Hardening: σ_y(ε̄ᵖ) = σ_y0 + H ε̄ᵖ + Q (1 − exp(−b ε̄ᵖ)); H′(ε̄ᵖ) = H + Q b exp(−b ε̄ᵖ).
- Trial state: σᵗʳ = σₙ + λ tr(Δε) 1 + 2G Δε (tensor form); p = tr σᵗʳ/3; sᵗʳ = σᵗʳ − p 1;
  ‖sᵗʳ‖ = (s:s)^{1/2} with shear components counted twice; qᵗʳ = √(3/2) ‖sᵗʳ‖.
- Yield check: φᵗʳ = qᵗʳ − σ_y(ε̄ᵖₙ). If φᵗʳ ≤ 0: σₙ₊₁ = σᵗʳ, ε̄ᵖₙ₊₁ = ε̄ᵖₙ, DDSDDE = elastic matrix.
- Otherwise solve r(Δγ) = qᵗʳ − 3G Δγ − σ_y(ε̄ᵖₙ + Δγ) = 0 by Newton from Δγ = 0, with
  r′(Δγ) = −3G − H′(ε̄ᵖₙ + Δγ). Update `DGAM = DGAM - RES/DRES`. The convergence test
  |r| ≤ 10⁻¹² σ_y0 is applied to the residual *before* each update, so at least one Newton step is always
  taken and the returned iterate is one step past the iterate that passed the test. At most 50
  iterations; on non-convergence PNEWDT = 0.25.
- Return: n̂ = sᵗʳ/‖sᵗʳ‖; sₙ₊₁ = (1 − 3G Δγ/qᵗʳ) sᵗʳ; σₙ₊₁ = sₙ₊₁ + p 1; ε̄ᵖₙ₊₁ = ε̄ᵖₙ + Δγ.
- **Eq. T (hand-coded consistent tangent, plastic branch):**
  D = K 1⊗1 + 2G (1 − 3G Δγ/qᵗʳ) I_dev − 6G² (1/(3G + H′(ε̄ᵖₙ₊₁)) − Δγ/qᵗʳ) n̂⊗n̂.
  In Voigt form with engineering shear: the I_dev block is δ_ij − 1/3 on the normal block and 1/2 on the
  shear diagonal; n̂⊗n̂ uses tensor (stress-like) shear components. This is the tangent of the *exact*
  discrete solution (implicit-function derivative). The OTI tangent of the transformed routine is the
  derivative of the *executed iteration* and is expected to approach Eq. T only as the iteration converges
  (Noether B3); measuring that gap is part of task R1.

## Known limitations (by design)
- NTENS = 6 only; no plane-stress branch; no NLGEOM/DROT handling; no temperature dependence.
- SSE, SPD and SCD are not updated.
- At qᵗʳ = 0 the elastic branch is always taken (φᵗʳ = −σ_y < 0), so the n̂ division is never reached; the
  OTI derivative at a purely hydrostatic state is nevertheless worth testing (Noether B5, Vera I4).

## Verification task R1 (owner proposed: Ada builds, Gauss and Curie review; Santiago authorises)
See `../../../missing-evidence.md`, task T4 (R1), for input, output and the completion criterion.
