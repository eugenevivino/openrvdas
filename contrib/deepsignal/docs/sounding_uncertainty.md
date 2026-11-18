# Sounding uncertainty

This module estimates the precision of a sounding and identifies the measured
input that dominates it. The first watch check is: if an alarm appears, slow or
steady the ship and check whether timing, motion, or sound speed is named before
using the sounding for a science decision.

## Normalized input contract

`NormalizedSoundingPacket` is the public adapter boundary. It carries event
time; system, head, swath, ping, beam, and sector IDs; local origin ENZ; launch
vector; two-way travel time; pose, rates, and lever arm; unit-tagged `q_names`
and `q_units`; a labeled joint covariance; installation ID; datum; frame;
validity mask; ancestry; and optional profile identity. ENZ uses metres and
positive-down Z. Angles use radians, time uses seconds, velocity uses m/s, and
covariance units are the products of their corresponding `q_units`.

KMALL adapters map public `#MRZ` two-way travel time, receive beam angle, sector
tilt, transmit transducer depth, and navigation. They bracket `#SKM` measured
motion at the correct transmit and receive times. Exact version-dependent
offsets and corrections remain disabled until verified. A straight homogeneous
ray is supported by the contract. Stratified data requires a profile ray
function or returns an incomplete-model result. Legacy `.all` and independently
decoded rays must enter through the same normalized contract. The module never
opens a socket or queries an instrument.

Detection variance appears exactly once. When detection error is correlated
with `q`, `detection_cross_covariance` supplies C for the signed cross term. A
zero C requires `detection_independence_source_id`. A clock offset is never
treated as its standard deviation, and RMS is never inferred from one absolute
offset. Missing shared cross-covariance produces an incomplete result or a
flagged sensitivity bound.

## Output fields

All derived fields are prefixed `TPU_`. `TPU_SoundingId` is text;
`TPU_Cov_ENZ_m2` is a symmetric 3 by 3 matrix; `TPU_VerticalSD_m` is a
nonnegative scalar; `TPU_Vertical95_m` contains separate lower and upper depth
endpoints; `TPU_HorizontalAxes95_m` contains major and minor full axes;
`TPU_HorizontalAzimuth_deg` is east of north modulo 180 and is null for a
circular ellipse. `TPU_DominantTerm`, `TPU_CalibrationId`, and
`TPU_IntervalTarget` are nullable text. The interval target is either one
sounding or a comparison and is never inferred from the calibration source.

`TPU_Score` is vertical half-width divided by science tolerance in metres, so
higher is worse and threshold 1 means the interval exceeds tolerance.
`TPU_Verdict` and `TPU_Reason` are text. `TPU_Support` is the independent block
count, `TPU_Persistence` is elapsed seconds, `TPU_SourceIds` is a text list, and
`TPU_Stale` and `TPU_Excluded` are booleans. Missing numeric results are null,
not NaN. Records retain event and record timestamps, raw fields, and existing
QC. Derived records include ancestry and source IDs in metadata.

An alert requires 60 continuous seconds above score 1 and clears after 60
continuous seconds below 0.75. A gap resets either timer. Record time drives
persistence, making replay causal and deterministic.

## Calibration and limitations

Vertical calibration selects one seed-declared representative from each
independent line block and needs at least 39 blocks in a matching regime. At
alpha 0.05, `k=ceil((B+1)*0.95)` and the 1-indexed kth ordered score is frozen.
Repeated pings add no support. Fits exclude holdout line, site, and time IDs with
a footprint buffer and preserve input hashes. Live lookup uses prior records
only.

The finite-sample guarantee is for disagreement with the independent reference.
At reference SD `0.1*s_z`, comparison variance is `1.01*s_z^2`; absolute-depth
coverage is approximate and reports that 1% variance inflation. Crossline-only
calibration produces a difference multiplier and cannot label absolute depth.
Horizontal coverage requires independent horizontal control.

Wrong covariance, motion or sound-speed double counting, new installation
epochs, common datum errors, or unsupported ray physics can defeat the check.
The output then remains uncalibrated or reports the missing component. This is
not survey-grade certification and never automatically rejects a sounding.

## Demo and operator knobs

The demo reads local JSON lines and writes local JSON lines. `science_tolerance_m`
is positive, normally 0.1 to 10 m, example 1 m. `alert_persistence_s` and
`clear_persistence_s` are nonnegative seconds, example 60. `clear_fraction` is
0 to 1, example 0.75. `max_records` is a positive bounded count, example 1000.
Calibration ID is a frozen table hash and installation ID must match exactly.

Desk checklist: the watch gets a plain cause and first action; technicians get
timing, covariance, source, and installation identity; science gets units,
datum, interval target, and calibration status; shore gets ancestry, block
support, exclusion, and deterministic replay fields. Browser and GPU checks are
N/A because this is an offline Python transform with text output.
