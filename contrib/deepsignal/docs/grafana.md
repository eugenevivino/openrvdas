# Grafana quality pack

The quality pack builds a Grafana dashboard and alert rules directly from an
OpenRVDAS cruise definition. It finds logger configurations containing an
`InfluxDBWriter`, uses that writer's bucket and measurement, and creates two
panels for each known field: a value panel keyed to its `_QC` flag and a stat
panel showing seconds since the last value. When a logger has heading and wind
fields, the dashboard also includes an optional OceanDataTools compass panel.

## Build

From the OpenRVDAS repository root, run:

```console
python3 -m contrib.deepsignal.grafana build \
  test/NBP1406/NBP1406_cruise.yaml --out /tmp/ds-grafana
```

The output is deterministic and contains `quality-dashboard.json`,
`quality-alerts.json`, and `dashboards.yaml`. Copy the two JSON files to
`/var/lib/grafana/dashboards/openrvdas`. Copy `dashboards.yaml` to Grafana's
provisioning dashboards directory, then restart Grafana. The provider polls the
dashboard directory every 30 seconds.

The default stale threshold is 300 seconds. Override it with
`--stale-after-s SECONDS`. The value must be a positive number.

Grafana must have a Flux-capable InfluxDB data source configured for the bucket
named in the cruise definition. The compass panel is marked optional because it
also requires the `oceandatatools-compass-panel` plugin. If the plugin is not
installed, the QC and freshness panels remain usable.

## Inputs and errors

Cruise YAML is loaded with `yaml.safe_load`. Hand-edited input is validated
before files are written. Errors are one line and identify the setting, the bad
value or condition, the expected form, and an example.

The generator does not modify incoming records. Missing values stay missing,
and freshness panels display the elapsed time from the most recent stored
value rather than estimating a replacement.

## Lead screenshot step

Outside the sandbox, the lead should provision the generated files in a test
Grafana instance, open the dashboard with live NBP1406 data, and capture a
screenshot showing green, amber, red, and grey QC states plus a stale panel.
