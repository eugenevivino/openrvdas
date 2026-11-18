# Fault-injection benchmark

Replay NBP1406 mast weather records with known faults and plausible shipboard
changes to measure detection speed, missed faults, and false alarms in an
OpenRVDAS Transform. Each scenario starts with a fresh detector instance.

## Run it in 5 minutes

From the repository root, use Python 3.12 with PyYAML available.

```sh
python3.12 -m contrib.deepsignal.bench run \
  --scenarios contrib/deepsignal/bench/scenarios.yaml \
  --detector contrib.deepsignal.bench.stub:StubThresholdDetector \
  --kwargs '{}' --output-dir bench-output
```

Open `bench-output/summary.md` for one row per scenario and
`bench-output/results.json` for the scores and injector truth intervals.
Omit `--output-dir` to write both files in the current directory. Input logs are
read from `test/NBP1406/mwx1` or `test/NBP1406/data/mwx1`. Use `--sample-root`
to point to a different copy of the NBP1406 directory.

Replace `--detector` with your Transform's `module:Class` and pass its
constructor arguments in the `--kwargs` JSON object. The transform receives one
DASRecord at a time with the fields from the source field's mwx1 message and
returns a DASRecord with a flag such as `MwxAirTemp_QC`. The stub uses sample
range limits with `{}`. Optional `minimum` and `maximum` kwargs set explicit
range limits.

Set `--flag-suffix _DG` or `--flag-suffix _SHIP` to read a different output
field, and `--threshold` to select its minimum alarm value. For `_QC`, the
default threshold of 3 counts suspect (3) and bad (4). A threshold of 4 counts
bad only. Missing (9) is a separate QARTOD status, so a dropout scored only
as missing will show as a missed detection. Custom suffixes use a numeric
comparison against the configured threshold.

## Scenarios

A scenario specifies `field`, one of `fault`, `trap`, or `injector`, optional
`params`, and `seed` (default 0). Built-in `start` and `end` are inclusive
offsets in seconds from the first sample, and default to the entire series.
Truth intervals are inclusive and use the unmodified source timestamps.
Replay follows source order while preserving any injected timestamp changes,
so clock resets remain visible and latency uses the original clock.

- **Drift** adds a linear offset at `rate_per_hour`, starting at zero.
- **Step** adds a constant `bias`.
- **Lag** applies a first-order response with a `tau_seconds` time constant.
- **Hysteresis** applies `rising_offset` or `falling_offset` according to direction.
- **Clock jump** shifts timestamps by signed `seconds`.
- **Clock reset** shifts timestamps backward by `seconds`. Set the window and
  shift so its first timestamp moves behind the preceding source timestamp.
- **Spikes** adds signed `size` to each of `count` samples chosen using the seed.
- **Flatline** holds the first value in the window.
- **Dropout** replaces values with `None`.
- **Front** adds the same `bias` to two linked fields on the same records, using
  `companion_field` for the second field and labeling the interval as a trap.
- **Turn** eases through a signed `degrees` sweep with wraparound at 360 and
  labels the interval as a trap. The sample uses relative wind direction as
  a proxy for the angular sweep of a turn.

Set `injector: package.module:function` to use a plug-in. It receives a list
of `(epoch_seconds, value)` pairs and keyword arguments for `seed` and
`params`, and returns a new list in the same source order and length plus
`[(start_epoch, end_epoch, name)]` truth intervals. Use the original sample
clock for truth, even when changing timestamps. For a plug-in that needs
another same-record field, set `companion_field` to pass its series as the
`companion` keyword argument. Scenario files with plug-ins and detector
references should come from a trusted source, since their modules are imported
and executed.

## Read the summary

- **Median latency** is the time to the first qualifying flag within each fault,
  summarized over detected faults. **Missed/total** counts intervals without a
  qualifying flag, with each spike scored as its own interval.
- **False flags/h** counts flagged samples per observed hour outside fault
  intervals, including samples in traps. **False alarms/ship-day** scales that
  rate to 24 hours. Consecutive flagged samples count individually.
- **Trap flags** counts flagged samples in traps. **Trap flags/h** uses time
  within traps as its denominator. Both hourly rates assign elapsed time to
  the preceding source sample. Rates with zero observed time show as `n/a`.
- **Missing flag samples** counts absent or nonnumeric verdicts, including when
  the configured suffix is wrong. A QARTOD verdict of 9 is a present verdict.

The sample spans part of a single cruise and the injected faults are
idealized. The 24-hour rate is an extrapolation from the replay. These results
do not establish performance on other cruises or naturally occurring failures.
