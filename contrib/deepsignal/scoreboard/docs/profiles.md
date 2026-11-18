# Scoreboard profiles

A profile describes one scoreboard model without adding Python code. Copy a
packaged profile from `scoreboard/profiles/` and save the edited file in
`local/scoreboard_profiles/`. A local file wins when it has the same name as a
packaged file.

The YAML `name` must match its filename. Choose `text`, `alpha`, or `modbus` as
the codec, then specify display limits and codec-specific framing. Set
`verified` to `unverified` until a datasheet or bench test supports the values.
Transport defaults are optional and may be overridden by logger configuration.

Load a profile by name:

```python
from contrib.deepsignal.scoreboard.profiles import load_profile
profile = load_profile('generic_ascii')
```

Configuration overrides merge into nested sections:

```python
profile = load_profile(
    'generic_ascii',
    {'transport_defaults': {'baudrate': 19200}},
)
```

Profiles are untrusted input. Loading uses safe YAML parsing and rejects unknown
keys, unsafe template fields, invalid escape sequences, incompatible transports,
and overlapping Modbus registers before any device operation. Keep literal byte
escapes such as `\r` and `\x02` in single-quoted YAML strings.
