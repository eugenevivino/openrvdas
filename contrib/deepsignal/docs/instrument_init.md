# Instrument initialization profiles

This module sends a reviewed, versioned sequence when an instrument opens and,
when configured, after reconnect or silence. Use core `PolledSerialReader`
`start_cmd` instead when one unchecked command at reader construction is enough.
It does not verify replies, reopen the port, or repeat after a power loss.

## Profile format

A profile requires `profile_id`, integer `version`, `reviewed_by`, `reviewed_on`,
free-text `source`, and a `steps` list. `instrument` names the audit subject and
`line_ending` is appended verbatim. Each step requires `name`, `class`, and
`send`. Optional settings are `expect`, `timeout_s`, `retries`, `pause_s`, and
`optional`. The only time template is `{utc:FMT}`. A `{secret}` placeholder gets
its value solely from the step's `secret_env` environment-variable name.

`query` is read-only, `setup` changes runtime settings, and `persist` changes
non-volatile memory or firmware. Readers send query and setup steps. Persist
steps run only through a confirmed manual command with `--allow-persist --yes`.
`reinit.on_reconnect`, `after_silence_s`, and `max_per_hour` control safe retries.
Profiles produced by a device pack or configuration wizard must use this format
and cite the reviewed manual in `source`; this module does not import either.

## Safety and audit

Only literal profile bytes are sent and a missing profile opens no connection.
Unreviewed profiles require explicit `allow_unreviewed` and warn once per run.
Every send and reply is appended as JSONL with UTC time, instrument, profile,
trigger, step, text, hex, match, and elapsed time. Audit files are never
truncated. Secret values are replaced by `***` in audit text and output.
Required mismatches abort initialization but not reading; optional mismatches
warn and continue. The hourly cap stops reinitialization while reading continues.
UDP is unsupported because it provides no reliable reply channel to check.

## Worked example

Validate and inspect without opening a connection:

```console
python -m contrib.deepsignal.instrument_init check contrib/deepsignal/configs/instrument_init_example.yaml
python -m contrib.deepsignal.instrument_init plan contrib/deepsignal/configs/instrument_init_example.yaml
```

After stopping the logger on the port, a tech can apply it explicitly:

```console
python -m contrib.deepsignal.instrument_init run profile.yaml --serial /dev/ttyUSB0 --baud 9600 --yes
```

A lead-run check on real hardware must happen outside the sandbox with a tech
present. Confirm the cited manual, cabling, serial settings, replies, restart
behavior, and append-only audit before unattended operation.
