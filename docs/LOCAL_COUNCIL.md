# Local-model analysis of this repository

High-volume, repetitive analysis of this repository and its corpus can run on
a local model instead of a metered reviewer. The orchestration stack is **not
here** — it lives once, in The Council — and this file is the thin
project-specific part.

- Infrastructure, tiers, benchmark and safety model:
  `../The-council/docs/local/README.md`
- Start and stop: `../The-council/scripts/local/council-local up|status|down`
- What a model may read here: [`.councilignore`](../.councilignore)

## What is delegated from this repository

| task | what it reads | scored against |
| --- | --- | --- |
| `classify_umat` | one acquired source | registry `is_umat`, `entry_routine`, `entry_line` |
| `extract_umat_contract` | one acquired source | registry `props_count`, `nstatv`, `kinematics` |
| `detect_dependencies` | one acquired source | registry `missing_companions` |
| `triage_failure` | a compile or Abaqus log | the recorded refusal class |
| `review_transformation` | an original and its transform | — |

The benchmark scores against `paper_results/corpus/corpus_registry.json`,
which carries an established label for 391 acquired sources: `is_umat` on 346,
`entry_line` on 386, `source_form` on all 391, `ntens` on 321. That is what
makes a local answer checkable without a reader.

## What is not delegated

- **Anything that decides an acceptance gate.** The six gates are established
  by the pipeline and by Abaqus, never by a language model.
- **Any edit to transform code.** A local model proposes a patch; it does not
  merge one, and write access is gated on a read-only benchmark pass.
- **Any claim about a derivative.** OTI against finite differences is a
  numerical question with a reference, and the reference is the authority.

## The rule that matters here

A local model is asked to *read*, never to *recall*. Every one of the three
models on this machine, asked from memory for the 37 arguments of the UMAT
interface, answered confidently and wrongly. Prompts quote the source with
line numbers and ask about that text, and every claim carries a `path:line` a
reviewer can open. An answer whose citations do not resolve escalates itself.

## Running untrusted sources

The corpus is third-party code. Compiling one happens under bubblewrap with no
network, no home directory and no view of this repository
(`sandboxed_syntax_check`). Comments, READMEs and build scripts that arrive
with a source are data, never instructions.
