# Depth consensus

`DepthConsensusTransform` passively compares depth values already present in an
OpenRVDAS record. It does not open a connection, write to a sonar, look up a
grid, or alter ship settings. Configure a later provider to place an expected
grid depth in the record when that comparison is wanted.

Depths differ when instruments use different transducer drafts, sound-speed
profiles, bottom-detection rules, frequencies, or footprints. Lost bottom lock,
side lobes, bubbles, steep terrain, and stale data can also produce disagreement.
Set each `offset_m` to convert depth below its transducer to metres below the
waterline.

## Output and response

* `Consensus` is the median of fresh sonar values. `SpreadPct` and each `Dev_*`
  quantify disagreement. A reference is compared but never votes in the median.
* `OddOne` identifies the sonar furthest from the available reference, or from
  the sonar consensus when no reference is available.
* `Alarm` waits for `persist_s` of record time. It clears only after the metric
  remains below 75 percent of `threshold_pct` for `clear_s`. `AlarmText` gives
  the source, values, threshold, and first check. Check bottom lock and draft,
  then sound speed, sea state, bubbles, terrain, and installation geometry.
* `Stale` lists sources whose last valid update exceeds `max_age_s`, including
  sources not yet observed. Stale values do not become zeros or enter a vote.
* `LostBottom` lists an invalid sonar after `persist_s` while another sonar is
  fresh. Check the named sonar display and transducer aeration first.
* `Step` lists a sonar that jumps by more than four times the threshold while
  the other updated sonars hold steady. Check for a side lobe or bottom-lock
  change first.

Records may be dictionaries, `DASRecord` objects, lists of either, or `None`.
Replay decisions use record timestamps, not the computer clock. Choose a prefix
that does not collide with input fields. The default output prefix is `DEPTH`.

## Configuration notes

Every source needs a `field`, a positive `max_age_s`, and a `role` of `sonar` or
`reference`. At least one sonar is required. `min_depth_m` suppresses comparison
alarms in shallow water where percentages are unstable. Non-numeric, negative,
zero, NaN, and infinite depth values are invalid. Configuration errors identify
the setting, rejected value, expected form, and an example.
