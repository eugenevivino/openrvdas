# Quality-weighted depth contract

`WeightedDepthTransform` is a causal, listen-only derived-data transform. It
accepts a dict, a `DASRecord`, a list of either, or `None`. `None` passes
through. Inputs, timestamps, existing fields, and QC are not mutated. The
transform validates finite depths, units, waterline reference, datum, event
time, age, ancestry, and footprint before estimation. Invalid, duplicate,
partial, stale, future, and unsupported observations are counted and excluded.

## Source and output records

Each source config has `field`, `time_field`, `role`, `family`,
`raw_parent_fields`, `offset_m` (m, positive down), `datum`, `max_age_s` (s),
`private_sd_m` (m), `shared_loadings` (dimensionless vector), and `footprint_m`
(along/across metres). `draft_sign` and `reference_surface` are required.
`ADCP_BTGood` is a percentage and is not reconstructed from PD0 quality bytes.
SBP conversion is allowed only with trace delay, heave, draft, and water-path
sound speed. Grid input requires independent source IDs, tide/datum, cell size,
and vertical uncertainty.

Every output name starts `WDEP_`. `Depth_m` and `SD_m` are nullable scalar
metres. `RelativeBias_m` and `PrivateVariance_m2` are nullable maps by family.
`FamilyWeights` and `HeldOutZ` are nullable maps, with the latter positive in
the source-deeper direction. `Datum` and `AnchorId` are nullable strings.
`Score` is the largest supported absolute held-out z score. `Verdict` is one of
GOOD/1, SUSPECT/3, FAULT_LIKELY/4, AMBIGUOUS/3, UNCORRECTABLE/4, or
POSTHOC_REVIEW/2. `Reason` is plain text, `Support` is an independent-family
count, `Persistence` is seconds, `SourceIds` and `Excluded` are string lists,
and `Stale` is boolean. Record time keys persistence; event time keys samples.

An alert needs 60 continuous seconds above 3 and clears after 60 continuous
seconds below 2.25. A gap resets both timers. Replay is causal and deterministic.
In watch language, first check whether the named sounder still has bottom lock
while the other two independent families agree.

## Estimator controls and desk checklist

The demo labels `process_acceleration_m2_s3: 0.01` as a vessel-profile example,
not a calibration. Huber cutoff is 1.5 standardized units; window is 120 matched
blocks; minimum is 20 blocks per edge; iteration limit is 10; convergence is
relative state change below 1e-6. Age limits should follow native intervals.
Bias priors and variance floors come from declared installation calibration.

The desk sees depth and uncertainty, contribution weights, relative bias
history, exclusions, persistence, and a plain reason. A two-family split is
AMBIGUOUS. One family is explicitly single-source with prior uncertainty.
Absolute blame is unavailable for common draft/heave, mobile bottom,
nonsynchronous footprints, or a grid sharing survey lineage. Corrections are
N/A: this module emits observations only and never changes raw data.

## Numerical evidence boundary

Pair learning uses the plain second central moment after a 5 scaled-MAD outlier
screen, freezes across alarms and runtime/datum changes, and never treats
consensus depth as another sonar. A narrower trim requires a declared noise law
and a stored, simulated consistency factor. Unknown residual cross-covariance
makes private variances UNIDENTIFIED. Known residual covariance is used in both
the pair equation and fusion covariance. Pair-fit misfit is gated at the 95th
percentile of 999 block-bootstrap resamples, with at least 30 independent blocks
per pair; a material misfit retains prior variances and makes attribution
AMBIGUOUS. Exact
ancestry copies collapse before whitening. Fit and holdout IDs are disjoint by
line/site/time plus footprint buffer. Field plumbing against NBP1406 and all
survey, recall, coverage, false-repeat, timing, and memory claims remain outside
this scaffolding lane and require separate receipts.
