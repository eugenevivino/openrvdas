# Stream health

Stream health identifies the earliest unhealthy stage and marks later stages as
affected. It does not probe a configured serial port or network endpoint. A
serial endpoint check only reads whether its filesystem path exists.

```text
sensor -> endpoint -> raw traffic -> parser -> time -> calibration -> derived -> store
   |          first non-OK stage is root cause          |              |
   +---------------- later stages are affected ---------+--------------+
```

Configure `module: contrib.deepsignal.stream_health.stream_health` and
`class: StreamHealthWriter`. See `configs/stream_health_example.yaml` for a
complete chain. The writer adds `ds_chain:<stream>:<stage>` and
`ds_chain:<stream>:root` fields. A stale configured key field becomes an
explicit null alongside `ds_age_s:<field>`.

States are `OK`, `DEGRADED`, `FAILED`, `UNKNOWN`, and `OFF`. Optional sources
that are not configured are `OFF`. Missing evidence is `UNKNOWN`; it is never
guessed. `TransitionTracker` waits for the configured hold time before emitting
a transition and limits emissions per stream within its rate window.

YAML is loaded with `yaml.safe_load`. Configuration errors identify the setting,
the received value, the expected shape, and an example correction.
