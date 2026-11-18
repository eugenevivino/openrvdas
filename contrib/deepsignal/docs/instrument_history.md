# Instrument history

The instrument history keeps a reviewable YAML record of which sensor supplied each field at any time.

## Turn it on in 5 minutes

1. Copy `contrib/deepsignal/configs/instrument_history_example.yaml`.
2. Give every instrument a unique `id`, quoted string `serial`, its fields, and time-ordered events.
3. Run `python -m contrib.deepsignal.instruments check your_file.yaml`.
4. Query a field with `python -m contrib.deepsignal.instruments at your_file.yaml TSG_Temp 2026-03-01T00:00Z`.

Times are UTC ISO 8601 (`2026-03-01T12:30Z`); a bare date means midnight UTC. Polynomial coefficients are lowest order first. Events are:

- `install`: `{time: 2026-03-01, type: install, position: "main lab"}`
- `remove`: `{time: 2026-09-30, type: remove}`
- `calibration`: `{time: 2026-03-01, type: calibration, cal_id: c1, coefficients: {TSG_Temp: [0.0, 1.0]}}`
- `firmware`: `{time: 2026-06-12T14:30Z, type: firmware, version: "2.1b"}`
- `repair`: `{time: 2026-08-02T09:00Z, type: repair, note: "replaced pump"}`
- `move`: `{time: 2026-04-01, type: move, position: "wet lab"}`
- `clock_source`: `{time: 2026-04-01, type: clock_source, source: gps}`
- `software_version`: `{time: 2026-04-01, type: software_version, version: "3.0"}`
- `note`: `{time: 2026-04-01, type: note, note: "inspection passed"}`
- `cleaning`: `{time: 2026-04-01, type: cleaning, note: "fresh water rinse"}`
- `pump_off`: `{time: 2026-04-01T12:00Z, type: pump_off}`
- `pump_on`: `{time: 2026-04-01T12:10Z, type: pump_on}`
- `valve`: `{time: 2026-04-01, type: valve, position: closed}`
- `power_cycle`: `{time: 2026-04-01, type: power_cycle}`
- `swap`: `{time: 2026-04-01, type: swap, replaces: tsg0, position: "main lab"}`

An `ERROR` identifies a contradiction that makes the registry ambiguous and makes `check` exit 1. A `WARNING` identifies metadata worth reviewing but does not fail the command. Each line names the instrument and problem. Optional `shares` entries (`id` plus `plumbing`, `intake`, `wake`, `cell`, or `clock`) record shared evidence; missing targets warn.

This registry does **not** change data or apply calibration coefficients. Applying calibrations is a later module.
