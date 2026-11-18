# Sub-bottom reflectors

This module marks coherent shallow reflectors and intervals where a water-bottom multiple can explain the same return. The first watch check is: compare the marked interval with heave, draft, gain changes, and the seabed reference before interpreting a bed.

## Input and provenance

Decoded traces contain `trace_id`, coordinates `x_m` and `y_m`, UTC `time_utc`, `delay_s`, `dt_s`, finite `samples`, `representation`, `source_hash`, `bottom_twt_s`, `bottom_sd_s`, and `pulse_resolution_s`. Representations are `raw_fm`, `signed_precompressed`, or `envelope`. Raw FM requires a supplied replica. The reader target is SEG-Y revision 1, fixed-length IEEE float traces, explicit byte order, microsecond sample interval, millisecond trace delay, signed coordinate scalar, declared coordinate units/reference, and UTC shot time. Unsupported encodings and units are rejected before trace allocation. SBP-derived bottoms must identify their shared raw parent and are weaker evidence.

## Output record

Every field is derived and prefixed `SBPH_`: `TraceId` (string), `HorizonId` (string), `PickTWT_s` (nullable seconds), `SupportCount` (independent blocks), `EnergyMargin` (standardized contrast), `Alternative` (nullable time or interval), `Gap` (boolean), `Resolution_s` (seconds), `Score` (additional predictive standardized contrast per supported trace), `Verdict`, `Reason`, `Support`, `Persistence` (independent footprint or line blocks), `SourceIds`, `Stale`, and `Excluded`. Higher score is stronger. A gap has no pick. Results apply only to their closed processing window and retain source record and interval keys.

The threshold is 1 standardized contrast unit, equal to 1.4826 raw log-envelope MADs when the floor is negligible. Defaults are five separated supports, positive blind gain, gap and entry penalties 2, maximum dip 0.2 ms/m, lag scale 0.1 ms/m, and three consecutive missing traces to terminate. For fixed draft and sound speed, order `m` timing is `mT + 2(m-1)d/c`, with standard deviation `m SD(T)`; uncertain draft and speed require the full gradient and covariance.

## Operations and limits

Bound trace count, sample count, window size, and maximum jump before DP allocation. Reject non-finite values, prefix collisions, unknown datum/frame/time base, duplicate or partial inputs, and torn records. Never extrapolate across a file gap. `AMBIGUOUS/3` retains both alternatives; `GOOD/1`, `SUSPECT/3`, `FAULT_LIKELY/4`, `UNCORRECTABLE/4`, and `POSTHOC_REVIEW/2` follow the evidence graph. This transform emits observations only and never changes SEG-Y or acquisition state.

Desk checklist: trace IDs and TWT picks are visible; gap intervals and alternatives are annotation-ready; shadow zones, gain discontinuities, and heave breaks appear in reasons; metres are N/A without independent sediment velocity. Real SBP29 revision, header offsets, UTC/time-zero, AGC, and pulse history remain inferred until ship evidence is checked.
