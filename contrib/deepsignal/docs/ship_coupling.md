# Ship-coupling discovery

This module finds replicated evidence that an environmental sensor partly measures the ship.

## Run it in 5 minutes

From the repository root, run:

```sh
python3.12 -m contrib.deepsignal.coupling atlas \
  --config contrib/deepsignal/configs/ship_coupling_atlas.yaml
```

Read `atlas.md` for a watch-friendly summary, `atlas.json` for complete parameters and
statistics, and `polar_<field>.csv` for sector medians and IQRs. `confirmed` means discovery
and named holdout passed FDR with a consistent sign and lag; `discovery_only` did not replicate;
`rejected` did not pass discovery FDR; `insufficient` has effective sample size below the limit.
`ship_artifact`, `environmental`, and `cannot_tell` are the invariance-control verdicts.

Replication protects against cruise-specific coincidences. Reciprocal-leg and time-shift
controls distinguish ship-fixed contamination from an Earth-fixed feature sampled along the
mission track. Circular-shift surrogate tests preserve autocorrelation, and family-wise BH or BY
controls false discoveries.

The live transform only reads a frozen atlas and adds scores, explanations, and QC-style flags.
It does **not** correct or delete observations, learn live, or alter timestamps. The short bundled
sample is a smoke test and proves nothing about a real ship; discovery needs archived cruises.
