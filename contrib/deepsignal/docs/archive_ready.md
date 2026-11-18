# Continuous archive readiness

This module scans closed cruise data files and keeps an append-only `manifest.jsonl`. Each observation
contains its path, size, SHA-256 checksum, timestamp bounds, record count, gaps, parser, configuration
version, and transfer status. A sidecar cache avoids hashing a file again while its size and modification
time are unchanged. Do not delete the cache during a cruise because it is also the checksum-change record.

## Configure and run

Copy `archive_ready/expected.yaml` and describe each dataset. `glob` is relative to the archive root.
`time_field` is a zero-based whitespace field, or a key for JSON Lines. A gap is more than three expected
cadences. `filename_date_pattern` is a regular expression used to check names. Metadata follows
`configs/archive_ready_example.yaml`. An optional `transfer_log` names a text file whose lines end with a
transferred path. Omit it when transfer state is unknown.

Generate a starting configuration from a loaded cruise definition:

```python
from contrib.deepsignal.archive_ready import generate_expected
proposal = generate_expected(cruise_definition)
```

Run the human report or JSON console output:

```console
python3.12 -m contrib.deepsignal.archive_ready.report /data expected.yaml metadata.yaml
python3.12 -m contrib.deepsignal.archive_ready.report --json /data expected.yaml metadata.yaml
DATASET                    FILES   COVERAGE
met                            31     99.20%
Checks: 1
coverage_under_95: Coverage is 91.00 percent, below the required 95 percent.
```

The command exits nonzero when a check needs attention. Missing transfer input remains `null`, never an
assumed success. Configuration errors identify the setting, observed value, expected form, and an example.
