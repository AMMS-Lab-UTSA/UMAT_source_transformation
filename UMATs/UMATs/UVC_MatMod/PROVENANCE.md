# UVCplanestress.for: provenance

| | |
|---|---|
| Upstream | https://github.com/ahartloper/UVC_MatMod |
| Path | `Abaqus/UVCplanestress.for` |
| Commit | `a4b8f6e27d0c9c4699332d75f68c562ee64932ae` |
| sha256 | `d25ee404fed5493ea479a3a38c8b0b59a25526dd5703fff9a6d0c99bf447b46e` (unchanged copy) |
| Licence | MIT, Copyright (c) 2019 Alexander R. Hartloper (`LICENSE` here; the upstream README states MIT) |
| Model | Updated Voce-Chaboche plasticity, plane stress (Hartloper, de Castro e Sousa and Lignos) |

`contract_v2.json` drives it as the author's own deck does:
`Abaqus/testing/Shell-Biaxial-UMAT.inp`, which the upstream README pairs with
this file, declares `*MATERIAL` with 11 constants and `*DEPVAR` 10:
PROPS = 179800, 0.3, 318.5, 100.7, 8, 0, 200, 11608.2, 145.2, 1026.3, 4.7
(E, nu, sigma_y0, Q_inf, b, D_inf, a, then C_k, gamma_k for two backstresses),
NTENS = 3, NSTATV = 10.

The file is the source of the CI-tier regression case
`umat/cases/umat-oti-curated--uvc-planestress/` (THIRD_PARTY_NOTICES.md 2e).
