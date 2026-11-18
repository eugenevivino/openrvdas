# Time health

`TimeHealthTransform` adds clock observations to records without replacing or
removing any incoming value. Configure it after timestamp parsing so each record
has an arrival `timestamp` and a `fields` mapping.

## Configuration

```yaml
class: TimeHealthTransform
module: contrib.deepsignal.time_health.streams
kwargs:
  stream_field: stream
  window: 120
  jump_s: 10
  streams:
    gps:
      source: embedded
      source_time_field: utc
```

`stream_field` names the field used to select a configured stream. `window` is
the number of latency and skew samples retained. `jump_s` is the absolute source
time change counted as a jump. An embedded timestamp may be epoch seconds, an
ISO 8601 datetime, or GNSS `HHMMSS[.sss]`. The GNSS form takes its date from the
record arrival timestamp, which handles the normal midnight rollover.

Hand-edited YAML must be read with `yaml.safe_load`. The transform itself takes
already parsed configuration and does not read files.

## Published fields

Host fields use `ds_time:host:*`, including `provider`, `synced`, `offset_s`,
`rms_offset_s`, `stratum`, `leap_status`, and `reference`. The host reader first
tries `chronyc -c tracking`, then `timedatectl show-timesync`. Each command has a
two-second timeout. If neither report is usable, the provider is `unknown` and
the host is reported unsynchronized.

Stream fields use `ds_time:<stream>:*`:

* `timestamp_source`: `host` or `embedded`.
* `latency_median_s` and `latency_p95_s`: arrival minus embedded source time.
* `backward_steps`, `repeats`, and `jumps`: cumulative event counts.
* `confidence`: `good`, `degraded`, or `bad`.
* `status`: present when an embedded timestamp is missing or invalid.

Pairwise skew uses `ds_time:<first>:<second>:skew_median_s`, with stream names
sorted for a stable field name. It is the median signed source-time difference.

## States and first checks

* `good`: the host is synchronized, its known absolute offset is at most 0.5 s,
  p95 latency is at most 2 s, and no backward source step occurred in the last
  ten minutes. First check that values continue to update.
* `degraded`: p95 latency exceeds 2 s or a recent backward step exists. First
  check the instrument link, source time field, and arrival queue depth.
* `bad`: the host is unsynchronized, its known absolute offset exceeds 0.5 s, or
  the configured embedded timestamp is missing or invalid. First check
  `ds_time:host:provider`, then the host time service and stream field name.
* `unknown` host provider: neither supported command returned a usable report.
  First check whether chrony or systemd-timesyncd is installed and running.

An unavailable measurement is shown as missing or `unknown`; it is not inferred.
