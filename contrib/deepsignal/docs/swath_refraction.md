# Swath refraction crossing check

## Status and first check

This module is an executable record contract and synthetic test scaffold. The
numerical estimator deliberately raises `NotImplementedError` until the next
sequential implementation lane. It is listen-only and never opens a socket,
subscribes to an instrument, changes a sound-speed profile, or proposes a
correction.

In watch language, the first check is: **compare the depth band named by the
alert with the latest independent cast, then inspect roll, heave, timing,
tide, datum, lever arms, and water-mass change before blaming sound speed.**
A result is a derived observation, not permission to apply a profile.

## Input record contract

The transform accepts `None`, a dict or `DASRecord` with `timestamp` and
`fields`, or a list containing either representation. `None` passes through.
A completed normalized fan uses schema `kmall-410224-normalized/v1` and carries
system, head, swath, counter, ping ID, line ID, head depth in m, one-way time in
s, launch vector or verified steering geometry, transmit and receive pose,
vertical datum, applied profile ID and hash, and raw source IDs. Timestamps are
UTC epoch seconds. The adapter must reject unknown versions, nonfinite values,
unknown uncertainty, partial fans, prefix collisions, unsupported multi-sector
or motion geometry, and any profile whose validity epoch does not cover the
ping. It must not extrapolate navigation or a file gap.

KMALL 410224 public symbolic inputs include `twoWayTravelTime_sec`,
`beamAngleReRx_deg`, transmit tilt and sector, sounding index,
`x_reRefPoint_m`, `y_reRefPoint_m`, `z_reRefPoint_m`,
`txTransducerDepth_m`, head attitude and navigation, waterline reference, and
the actual applied SVP profile and time. Variant offsets, corrections, fan
assembly, head reference, waterline sign, and transmit versus receive epochs
remain unverified. No such geometry may enter the ray operator until it is
version checked and independently reproduces vendor XYZ within combined ray
and pose uncertainty.

Live limits are 1 to 32 angular bins per ping, 1 to 128 matched cells per solve,
and at most one solve per 30 s. The defaults are 32 bins, 128 cells, and 30 s.
Full resolution processing is reserved for offline use. A versioned #161 prior
provides at most two basis modes and covariance in (m/s)^2, its prior ID,
ancestry, and source hashes. A cast-only covariance must be explicitly supplied
and labeled. Evidence reused by a prior is rejected as validation evidence.

## Output record contract

The output retains the input record timestamp, event timestamp, raw fields,
metadata and QC. Derived provenance has its own schema version, source hashes,
lineage ID, software version, config hash and interval keys. JSON null is used
where a quantity is unavailable.

| Field | Unit, shape, nullability and direction |
|---|---|
| `REFR_ModeVector` | At most two vectors over the prior depth knots, unitless, nullable. Only retained visible combinations appear. |
| `REFR_ModeAmplitude_mps` | One value per retained mode in m/s, nullable. Signed against the documented basis. |
| `REFR_ModeSD_mps` | Posterior SD per retained mode in m/s, nullable. Lower is more certain. |
| `REFR_DataRank` | Integer algebraic `rank(G)`, never confused with visibility. |
| `REFR_VisibleModes` | Count of singular values of `G P^(1/2)` at least 1. |
| `REFR_OuterResidual_m` | Measured outer-beam misclosure in m, nullable. Magnitude is worse. |
| `REFR_LikelihoodInfo` | Object with `lambda`, `v`, basis and metadata. The frozen-Huber form is labeled `local_quadratic_approximation`; fixed Gaussian weights are labeled `exact_projected_gaussian`. |
| `REFR_PriorId` | Versioned prior ID or null for no accepted prior. |
| `REFR_CrossingIds` | Nonempty list of independent line-pair IDs, or empty when excluded. |
| `REFR_Score` | Maximum retained absolute posterior amplitude divided by posterior SD, nullable. Higher is worse; watch threshold is 2 and also requires independent residual improvement. |
| `REFR_Verdict` | `GOOD`, `SUSPECT`, `FAULT_LIKELY`, `AMBIGUOUS`, `UNCORRECTABLE`, or `POSTHOC_REVIEW`. |
| `REFR_Reason` | Plain explanation, never null. |
| `REFR_Support` | Object with independent evidence blocks, row counts, angular and depth support. |
| `REFR_Persistence` | Object with record-time above and below durations in s. |
| `REFR_SourceIds` | Raw, calibration, clock, navigation and parent-fit IDs. |
| `REFR_Stale` | Boolean. True means freshness bounds failed. |
| `REFR_Excluded` | List of objects containing source ID and explicit reason. |

Record keys are `(system, head, swath, counter, ping_time)`. Crossing interval
keys add line pair, site and profile validity epoch. A live alert requires 60 s
continuously above threshold and clears after 60 s below 75 percent of the
threshold. A gap resets both timers. Record time controls persistence so replay
is causal and deterministic.

## Estimator contract

For residual `r0 + J alpha + H eta`, whiten and project nuisance columns, then
form `G = (I - Q Q^T) W J` and `r_w = (I - Q Q^T) W r0`. Frozen final robust
weights produce local information `Lambda = G^T G` and `v = -G^T r_w`.
`rank(G)` is the algebraic data rank. Visibility is separately determined by
singular values of `G P^(1/2)` at least 1. Shared pings are stripped or carried
in covariance. Terrain slope contributes `-g^T d(Delta x)/d alpha`.

A turning ray where `|p c| = 1` is marked turned and excluded without division.
Central differences use 0.05 m/s and must converge when halved. A rank-zero
result is `AMBIGUOUS`, reports competing roll, datum, tide, heave, timing and
water-mass causes, and offers only a cast check. Registration gaps are
`POSTHOC_REVIEW`.

## Configuration knobs

| Knob | Unit, range and example |
|---|---|
| `max_angular_bins` | Count, 1 to 32; example `32`. Bounds live allocation. |
| `max_matched_cells` | Count, 1 to 128; example `128`. Bounds solve rows. |
| `minimum_solve_interval_s` | Seconds, at least 30; example `30`. |
| central difference step | m/s, fixed `0.05`, with a half-step convergence check. |
| visibility cutoff | Observation SD, fixed `1`. |
| score threshold | Posterior SD ratio, fixed `2`. |
| alert and clear duration | Record-time seconds, fixed `60` and `60`. |

The offline demo config declares a local synthetic fixture, the transform and a
local text log writer. It makes no network connection. Its normal record path
is intentionally red until the numerical lane implements the estimator.

## Desk usability checklist

* Depth band and expected new-line outer-beam improvement: required result.
* Applied profile, prior ID, crossings, lineages and exclusions: required.
* Plain reason plus competing causes: required.
* Alarm first check: stated above.
* Automatic cast trigger: N/A because triggering is banned and this module is
  derived-observation only.
* Automatic profile or ledger change: N/A because a trusted, allowlisted human
  review outside this module is required.
* Real-cruise claim: N/A in this scaffold. DCDB/R2R candidates, actual crossing
  geometry, casts and applied profile epochs remain inferred and unverified.
