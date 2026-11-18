# Sound velocity consistency monitor

Sound velocity at the multibeam transducer controls how the sonar steers and
positions its beams. A wrong value can bend the apparent seafloor and leave
refraction artifacts across the swath. `SVConsistencyTransform` passively
compares sound velocities that other instruments or modules already provide.
It does not calculate sound speed, contact a sonar, or change any setting.

Configure `sources` with a role, input `field`, and maximum age in seconds.
Use `null` for a cast that remains valid until replaced. `threshold_ms` is the
allowed spread, `persist_s` prevents brief spikes from alarming, and `clear_s`
requires a stable recovery. Values outside `valid_range` are not compared.
All timing uses record timestamps, so replay results are repeatable.

## Output fields

With the default `prefix: SV`, the transform adds these fields only on records
that contain a configured input:

* `SV_Spread`: maximum minus minimum of the fresh, valid sources, or null when
  fewer than two are available.
* `SV_Diff_<a>_<b>`: absolute difference for each fresh source pair.
* `SV_OddOne`: source farthest from the median of the other sources when at
  least three are fresh and its distance exceeds the limit, otherwise empty.
* `SV_Alarm`: 1 after the excessive spread persists, otherwise 0.
* `SV_AlarmText`: plain alarm and first action, or empty when not alarming.
* `SV_Fresh`: number of valid, fresh sources used.
* `SV_Stale`: comma-separated roles excluded because they are too old.
* `SV_CastAge_s`: age in record seconds of the latest cast, or null before one
  arrives. This field is present when a `cast` role is configured.

## What to check first

Read the named source and values in `SV_AlarmText`. First check which sound
velocity input SIS is using and whether its timestamp is current. Then inspect
the hull probe and TSG for fouling or bad flow. If the water column may have
changed, take a cast. The alarm is advice only and never sends data to SIS.
