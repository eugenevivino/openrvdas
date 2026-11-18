# Calibration and units registry

The registry is the authoritative, effective-dated record of coefficients used to create derived
sensor fields. It never replaces a raw field. `CalibrationTransform` adds `<field>_cal` and
`<field>_cal_version`, or `<field>_cal_state: none` when the sensor and field are known but no entry
is valid at the record time.

## Configure OpenRVDAS

```yaml
- class: CalibrationTransform
  module: contrib.deepsignal.cal_registry.calibration_transform
  kwargs:
    registry_path: contrib/deepsignal/cal_registry/registry.yaml
    sensor_id: tsg1
```

Registry files contain a top-level `calibrations` list. Each item requires `sensor_id`, `serial`,
`field`, `units_in`, `units_out`, `form`, `coefficients`, `valid_from`, `certificate`, `entered_by`,
and `note`. `valid_to` and `checked_by` are optional. Times use ISO 8601, preferably UTC with a `Z`
suffix. Validity is inclusive at `valid_from` and exclusive at `valid_to`, so adjacent entries can
meet at the same instant. Overlapping entries for one sensor and field are rejected.

An item is verified only when `checked_by` exists and differs from `entered_by`. Certificate values
may be paths or document-store identifiers. The certificate value is also the version retained on
each derived record.

## Formula definitions

* `linear`: `y = a0 + a1*x`, with exactly two coefficients.
* `polynomial`: `y = sum(ai*x^i)`, with one to six coefficients, allowing order 0 through 5.
* `steinhart_hart`: `T = 1/(A + B*ln(R) + C*ln(R)^3)` in kelvin.
* `table`: linear interpolation among sorted `[x, y]` points. Values outside the table use the
  nearest endpoint.

## Units and dependency checks

`check_unit_suspicion(quantity, units, values)` returns warnings only. It recognizes temperature
(`degC`, `K`), conductivity (`S/m`, `mS/cm`), pressure (`dbar`, `hPa`, `kPa`), speed (`m/s`, `kn`),
resistance (`ohm`), and voltage (`V`, `mV`). It never changes a value or a configured unit.

`find_affected(sensor_id, config_paths, sensor_fields)` safely loads cruise YAML and returns named
outputs from transform configurations that consume one of the supplied sensor fields. Missing and
stale relationships are therefore visible as an empty result, not guessed.

## Audit and errors

`CalibrationRegistry.record_change()` writes one JSON object per line to an append-only
`changes.jsonl` file. A caller integrating the shared change recorder can use it instead when that
module is available. Registry YAML is loaded only with `yaml.safe_load`. Configuration errors are a
single line that identifies the setting, observed value, expectation, and an example correction.
