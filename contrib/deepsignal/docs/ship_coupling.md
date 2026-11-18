# Ship-coupling discovery

The offline atlas tests whether environmental sensor residuals vary with ship state and replicate in an independent holdout.

## Run it in 5 minutes

From the repository root, run

```sh
python3.12 -m contrib.deepsignal.coupling atlas --config contrib/deepsignal/configs/ship_coupling_atlas.yaml
```

The sample reads NBP1406 mast weather MET temperatures, PUS port relative-wind directions, GPS speeds in knots and gyro headings. Discovery uses the first 14 minutes of August 1, 2014 UTC. Holdout starts at 00:14 UTC. The short sample exercises the pipeline. It cannot establish ship contamination.

Read `atlas.md` in `contrib/deepsignal/coupling/tmp/ship-coupling/` for the verdict. The accompanying `atlas.json` contains the inputs, split bin counts, resolved parameters, per-fit seeds and diagnostics. Confirmed fields with populated polar cells also have a `polar_<field>.csv` with the code version, parameters and seeds.

## Archived cruises

Supply `input_csv` with one observation per line. Use epoch seconds or ISO timestamps in the `timestamp` column. The optional `cruise` and `regime` columns contain text. Other columns contain numbers or empty cells. A malformed line contributes to the warning count. Timestamped raw message streams can use the column mapping in the sample config. Each stream requires a path and message names. Column zero contains the message name.

Both named splits are required. Give each a half-open UTC time range with `start` and `end`, a list of `cruises`, or both. The selections must be disjoint. Bind instrument channels with `heading_field`, `direction_field`, `sog_field`, `latitude_field` and `longitude_field` as needed. A directly measured ship-relative direction can use `relative_heading_field`. Position and headings use degrees.

The engine bins each split independently on its cruise clock. It averages values within a bin, using circular means for directions, then subtracts a centered rolling median from each environmental field. Empty bins and unknown regimes retain their positions. SOG, shortest-arc heading rate and speed change determine the regime. A supplied label can identify a bin when SOG is unavailable.

## Reading the evidence

Each hypothesis names a field, ship variable and regime. Positive lag pairs the field at bin `t` with the ship variable at `t + lag`. Effect, effective size and paired moving-block confidence limits use the winning alignment. The surrogate test repeats the entire lag search after each circular shift. Shifts and resampled blocks stay within cruises.

The `families` mapping assigns field lists to FDR families. Standard meteorological, ocean, acoustic and navigation fields have defaults. Additional fields default to `met_vs_ship` unless a partition is supplied. Use an explicit partition for instrument-specific names. BH or BY runs independently within each family in each split.

- **Confirmed** means both splits pass FDR with the same effect sign and a best lag within one grid step.
- **Discovery only** means discovery passes and the holdout fails to replicate.
- **Rejected** means the discovery p-value fails FDR.
- **Insufficient** means discovery lacks a usable estimate or test. The usual minimum effective size is 30. Sparse overlap, undefined correlation or no legal surrogate shifts can also leave the p-value unavailable.

The reciprocal control matches distinct transit segments with positions within 10 km, times within 12 hours and headings within 30 degrees of opposite. It compares median residuals on the winning lag's ship clock. The default requires at least two matched pairs and 75% agreement. A ship vote requires reversed relative headings, a residual sign flip larger than within-leg variation and a change consistent with the fitted sign. Similar residuals at the matched positions support an environmental vote. Mixed evidence yields `cannot_tell`.

A `ship_artifact` also requires both 12-hour and 24-hour shifts to have support in both splits. Each shifted absolute effect must be smaller than its unshifted effect and at most `shift_effect_limit` (default 0.2). The JSON records the signed effects by split and the larger magnitude for each shift. Reciprocals that stay fixed in Earth coordinates yield `environmental`. Missing controls preclude a ship verdict.

Polar cells group residuals by confirmed regime, heading sector and speed band. Default speed edges are 1, 5 and 10 knots. An observation at an edge enters the higher band. The table gives median, interpolated IQR and count. It also summarizes observed changes across turns exceeding 60 degrees within five minutes at steady speed, using the five-minute residual medians before and after.

## Live QC

The logger example loads a small synthetic frozen atlas. The transform scores only confirmed `ship_artifact` evidence in the matching regime and cell. The healthy spread is the field-wide IQR after subtracting each calibration cell's median residual. The score is the absolute cell median divided by this spread, clipped to one. A zero or unavailable spread yields QC 2.

QC is 1 below 0.3, 3 from 0.3 and 4 from 0.7. Missing ship state or calibration yields QC 2. A missing or nonfinite measurement yields QC 9. The transform annotates a copy, preserves timestamps and existing annotations, and never corrects, deletes or learns from live measurements. Regenerate older discovery atlases before using them for live scoring.
