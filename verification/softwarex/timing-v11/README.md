# Timing scripts and run files (V11 reproducibility package)

These are the performance measurements the article's performance supplement
cites. They are copied unchanged from the V11 reproducibility package
(`UMAT_OTI_V11_reproducibility.zip`, SHA-256
`eefd41e455a451c214370c655c1fa65ffaf5ef49440ece982844659afeb1d2cc`, files
dated 2026-09-10), folders `src/` and `bench/`.

| File | What it is |
|---|---|
| `src/benchmark.py` | the first V11 performance script: one-time costs (module generation, transformation, compilation) and per-evaluation costs, with repetition counts and spread; `bench/bench.log` is the console output of a run (its `bench/bench.json` is not in the package) |
| `src/bench2.py` | per-evaluation cost of the Model A material point over a 20-increment path: original, transformed at order 1, and a centred-difference tangent; writes `bench/bench2.json`; `bench/bench2.log` holds the console output of the runs |
| `src/bench3.py` | OTI runtime module scaling: generation cost, source size and compile cost; writes `bench/bench3.json`; `bench/bench3.log` is its console output |
| `src/bench4.py` | peak compiler memory for the generated OTI runtime module; writes `bench/bench4.json` |

Limits, stated so that these files are not read as more than they are:

- They were run on the development code of 2026-09-09, on the machine the
  files record (Linux), not on version 1.2.0.
- The scripts hard-code the checkout path `/home/claude/repo` and the output
  folder `bench/` relative to the working directory; to rerun them, change
  `REPO` to a checkout of the code to be timed.
- The recorded machine is a 2-core Intel Xeon at 2.80 GHz with 7.8 GiB under
  Linux (`bench/bench.log`). Repetition counts and spreads are in the run
  files; process launch is included in the per-evaluation times.
