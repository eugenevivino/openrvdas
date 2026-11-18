# Sensor onboarding wizard

This five-minute workflow proposes a logger configuration without editing a cruise file.

1. Capture roughly one minute of unchanged, line-oriented instrument output in `capture.txt`.
2. Identify and trial a serial instrument:
   `python -m contrib.deepsignal.onboard capture.txt --serial /dev/ttyUSB0 --baud 9600`.
3. Review the reported device type, parse count, fields, units, and up to five failed lines.
4. Preview additions to a cruise definition with `--cruise local/cruise.yaml`.
5. Save a separate proposal with `--write onboard-proposal.yaml`. The command refuses to
   overwrite a file. Review and merge that new file through the vessel's normal configuration
   process.

For UDP input, replace the serial options with `--udp 5000`. A capture below 80% parse coverage is
reported as **No known device matched** and produces a regex-free raw logger. Input and cruise files
are never modified. The proposal header records the absolute capture path and proposal date so stale
captures are visible during review.

Errors name the setting, observed value, expected value, and a valid example on one line. Device YAML
is treated as untrusted input and read with `yaml.safe_load`; no network access is used.
