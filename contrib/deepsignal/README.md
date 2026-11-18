# DeepSignal

DeepSignal is a set of open source add-ons for OpenRVDAS. It aims to help
everyone aboard a research vessel get more out of the ship's underway data:
the science party, the bridge, technicians, and shore support.

## Vision

- **Get the basics exactly right.** Averages, units, and timestamps that a
  scientist can trust, with missing data shown as missing, never filled in.
- **Match what ships already rely on.** Cover the jobs that systems like
  Scripps MetAcq and CORIOLIX do, in open source, on top of OpenRVDAS.
- **Better displays.** Clear, glanceable views for each audience, beyond
  what a general dashboard tool gives out of the box.
- **Smarter data.** Methods that catch sensor drift, compare sensors that
  measure the same thing, and flag problems early, always proposing rather
  than silently changing data.

Everything here plugs into a standard OpenRVDAS install. Nothing in core
OpenRVDAS has to change.

## Layout

The folder mirrors core OpenRVDAS:

```
contrib/deepsignal/
  logger/transforms/   - transforms, loaded with module: contrib.deepsignal.logger.transforms....
  configs/             - sample logger configs
  test/                - unit tests, mirroring the code layout
```

## Modules

### VectorWindAverageTransform

`logger/transforms/vector_wind_average_transform.py`

Averages wind as vectors over a time window, so winds from 359 and 1
degrees average to 0, not 180. Each sample is weighted by its speed, which
is the standard vector-mean wind. It can also report the plain mean speed,
the highest speed in the window (gust), steadiness, direction spread, and
the number of samples used. It never fills gaps: a window with too few
good samples is reported as missing, and a calm window gives no direction.

Use it after core `TrueWindsTransform` to average true wind. For a single
angle such as heading or course, core `InterpolationTransform`'s
`polar_average` already does the job.

```yaml
  transforms:
  - class: VectorWindAverageTransform
    module: contrib.deepsignal.logger.transforms.vector_wind_average_transform
    kwargs:
      window: 60
      min_count: 30
      winds:
      - speed_field: PortTrueWindSpeed
        direction_field: PortTrueWindDir
        prefix: Avg1m
```

Full options are in the module's docstring. A runnable sample using the
NBP1406 test data is `configs/vector_wind_average_logger.yaml`.

## Running the tests

From the top of the OpenRVDAS tree:

```
pytest contrib/deepsignal/test/
```

## Requirements

No packages beyond those core OpenRVDAS already needs.

## License

Same as OpenRVDAS (MIT).
