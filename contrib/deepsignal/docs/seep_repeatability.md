# Seep repeatability record contract

This offline transform asks, in watch language: **does the promising feature survive the
next independent crossing at the same seabed position, rather than staying in the beam?**
It never commands a survey pass and never identifies methane or estimates gas discharge.

## Input and processing window

Input is `None`, a decoded record dictionary, a `DASRecord`, or a list of either record
type. `None` passes through. Records retain timestamp, fields, QC, and ancestry unchanged.
One result is emitted only for the declared `window_id`. Required voxel fields are event
time, line and trace IDs, head/system, ping counter, swath/fan, EN position in metres,
height above bottom in metres, footprint and range in metres, beam angle in degrees,
linear local-background-subtracted intensity, noise covariance block, insonified volume,
gain/TVG, runtime hash, frequency in Hz, calibration state, and coverage mask. Navigation
uses an earth EN frame and a declared datum. Optional EK and ADCP records must state
frequency, frame, calibration, QC, and parent IDs. Missing optional channels remain missing.

Only public KMALL 410224 is reserved for a future byte adapter. Its field offsets, signed
dB amplitude scale, TVG correction, partial-fan handling, and sidelobe limits are
unverified, so byte ingestion is disabled. Decoded rows are the supported contract.
Inputs are bounded before allocation, tiles are at most 256 by 256 cells by 128 heights,
and sparse visited voxels are streamed. Torn, stale, duplicate, partial, non-finite,
unsupported, colliding-prefix, mixed-frame, or ancestry-invalid input is counted and
excluded. No file gap is extrapolated and no cruise cube is allocated.

## Result fields

All fields occur under `fields` on a derived record with its own provenance. Scores increase
with support. Null means not observable or not estimable, never zero.

| Field | Unit, shape, and meaning |
| --- | --- |
| `FLARE_Anchor_EN_m` | m, nullable length 2, shared earth-frame bottom anchor |
| `FLARE_AnchorSD_m` | m, nullable non-negative scalar registration uncertainty |
| `FLARE_FeatureScore` | dimensionless nullable scalar, earth-fixed penalized fit gain |
| `FLARE_NullScore` | dimensionless nullable scalar, best beam-fixed or layer gain |
| `FLARE_RepeatLines` | count, non-negative integer independent crossing lines |
| `FLARE_Coverage` | fraction, nullable scalar in 0 to 1 common covered slice |
| `FLARE_RelativeIndex` | nullable scalar; pass ratio only with at least 0.8 coverage |
| `FLARE_IndexUnits` | `relative_linear_power_m2` for EM or `m` for calibrated Q-star |
| `FLARE_HeightBand_m` | m, length 2 inclusive slice bounds, default 10 to 15 |
| `FLARE_Score` | nullable dimensionless repeat gain over the best null |
| `FLARE_Verdict` | `REPEAT`, `CANDIDATE`, `AMBIGUOUS`, or `MISSING` |
| `FLARE_Reason` | stable code plus plain explanation for verdict or missing value |
| `FLARE_Support` | independent evidence block count and search-adjusted p value |
| `FLARE_Persistence` | independent trace/line count, unit `independent_lines` |
| `FLARE_SourceIds` | list of deduplicated raw, calibration, clock, nav, and fit IDs |
| `FLARE_Stale` | boolean, true when the documented window is no longer current |
| `FLARE_Excluded` | list of reason and count objects for rejected observations |

`FLARE_Support` also states whether the root is observed. A footprint-extrapolated root
withholds a confirmed anchor. Relative power is averaged in linear units and is undefined
for a near-zero first pass. Search p is `(1 + exceedances) / (1 + shifts)` after at least
199 stratified whole-line shifts preserving within-line correlation. Persistence does not
count correlated voxels separately.

## Knobs and desk response

`window_id` is a required stable interval key such as `line-42-crossing-2`.
`height_band_m` is two metres values, normally `[10, 15]`, within visible water column.
Rise templates are fixed at 0.1, 0.2, and 0.4 m/s. Tube widths are one and two footprints;
anchor spacing is one footprint; fallback tilt is bounded to -0.5 to 0.5 horizontal m per
vertical m. The first alarm check is coverage, observed-root status, heading separation,
and backgrounds on both sides. Then inspect excluded counts, runtime/calibration hashes,
and whether earth-fixed gain exceeds both nulls. One line remains a candidate. A repeat
needs at least 30 degrees wrapped heading separation, distinct ray paths, p at most 0.05,
root visibility, and gains over both nulls. Quantitative comparison needs at least 80
percent common coverage and compatible settings. No CI is issued without independent
blocks. Shared EK/EM parents count once. Bad navigation, incompatible gain, current
mismatch, no base, fish, turbidity, sidelobes, and uneven insonification are explicit
limitations. Cross-setting EM comparison, density, methane identity, and gas conversion
are N/A because the observations cannot support them.
