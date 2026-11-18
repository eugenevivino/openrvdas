# Cruise configuration from an instrument inventory

`contrib.deepsignal.config_gen` turns one hand-edited acquisition inventory
into an OpenRVDAS cruise definition. It does not start or change any logger.

## Run it

Preview the generated YAML on standard output:

```sh
python3 -m contrib.deepsignal.config_gen \
  contrib/deepsignal/configs/config_gen_example.yaml
```

Compare it with the cruise definition currently deployed, then write a new
file after reviewing the diff:

```sh
python3 -m contrib.deepsignal.config_gen acquisition.yaml \
  --history instrument_history.yaml --diff current_cruise.yaml
python3 -m contrib.deepsignal.config_gen acquisition.yaml \
  --history instrument_history.yaml --out proposed_cruise.yaml
```

`--out` never overwrites a file. Generation errors are one-line messages on
standard error and the command exits nonzero. History mismatches are warnings:
they do not silently add, enable, or remove instruments.

## Acquisition fields

Start with `config_gen_example.yaml`. `cruise` supplies the cruise id and date
range. `defaults.logfile_root` is the root of each instrument's raw log path;
`defaults.cds` is the cached data server. `defaults.device_definitions` is the
glob passed unchanged to `ParseTransform` (normally
`contrib/devices/*.yaml`). Each instrument needs a unique `id`, a known
`device_type`, and exactly one `serial` or `udp` transport mapping. Set
`enabled: false` to keep the instrument represented only in the off mode.

The supported modes are `off`, `monitor`, and `log`. Monitor parses records
and sends them to the cached data server. Log also writes raw records beneath
`<logfile_root>/<id>/raw/<id>`.

## Reproducibility and safety

All input is loaded with `yaml.safe_load`; no input expression is executed.
The header records each input path and SHA-256 digest. Its UTC time comes from
the newest input file modification time, so unchanged inputs regenerate
byte-identically. The YAML mapping order follows inventory order.

Review the unified diff before deploying. Device paths, serial settings,
ports, cached-data address, and log root are emitted exactly as entered; the
generator does not probe hardware or guess missing settings.
