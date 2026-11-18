# Alarm-linked vessel runbooks

Runbooks keep vessel-specific recovery knowledge beside the configuration. Each stream has one Markdown
file. The YAML front matter is machine-readable, while the remaining Markdown is returned as plain text.
The module does not render HTML.

## Complete TSG example

```markdown
---
stream: tsg1
endpoint: /dev/tty_tsg1
baud: 9600
format: SBE21
power: Science rack PDU A, outlet 4
spare_location: Main lab, instrument spares cabinet, shelf 2
escalation: Call the on-watch marine technician, then the science systems manager.
causes:
  - check: Confirm the PDU outlet and SBE 21 display are on.
    fix: Reset outlet 4 once, then replace the power supply from spares.
    stages: [read]
  - check: Compare a raw line with the active SBE21 parser definition.
    fix: Select the matching parser definition and preserve the raw sample with the alarm.
    stages: [parse]
owner: Marine technician
---
# Thermosalinograph 1

Check seawater flow before changing software. The serial cable terminates on patch panel port 7.
```

Cause order is operator priority. A cause with no `stages` applies to every failing stage. Stage names are
vessel-defined strings shared with alarm configuration.

## Python use

```python
from contrib.deepsignal.runbooks import runbooks

runbooks.load_all("contrib/deepsignal/configs/runbooks_example")
alarm_help = runbooks.for_alarm("tsg1", "read")
runbooks.record_fix("tsg1", "Reseated serial cable", "A. Tech")
```

`for_alarm` returns only JSON-safe values. It includes at most three fixes, newest first. `record_fix` is
the only runtime write path and appends one JSON object per line to `fixes.jsonl`.

## Command line

```console
python3.12 -m contrib.deepsignal.runbooks --directory RUNBOOK_DIR show tsg1 --stage read
python3.12 -m contrib.deepsignal.runbooks --directory RUNBOOK_DIR check STREAM_CONFIG.yaml
python3.12 -m contrib.deepsignal.runbooks --directory RUNBOOK_DIR draft tsg1 CRUISE.yaml
```

`check` exits nonzero for a missing runbook, missing owner, draft older than 30 days, or cause without a
check. `draft` reads the stream's `port_tab` entry and leaves unknown vessel facts visibly marked
`UNKNOWN`. Its owner remains `DRAFT` until a person verifies and edits it.
