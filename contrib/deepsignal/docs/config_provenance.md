# Configuration provenance

The configuration provenance module keeps immutable, content-addressed YAML
snapshots and an append-only JSON Lines audit trail. It does not require Git.
The default store is `/var/lib/deepsignal/config-history/`; deployments can set
a different directory.

## Python API

`ConfigHistory.snapshot(paths, who, note)` safely parses each hand-edited file
with `yaml.safe_load`, writes one `<sha256>.yaml` snapshot, appends an event to
`history.jsonl`, and returns the version hash. Repeated content reuses the same
snapshot while retaining every audit event. A non-empty note is required for
high-risk changes.

`semantic_diff(old, new)` is a pure function returning JSON-safe dictionaries.
It recognizes source, serial, parser, transform, writer, logger, rename, mode,
calibration, and units changes. `ConfigHistory.diff` also supplies a stable raw
unified diff. `ConfigHistory.drift(baseline, current)` returns only semantic
differences, so YAML comments and mapping order do not create drift.

`ConfigWatcher.poll()` checks the configured cruise and device files. Call it
every 30 seconds. An external content change is stored with actor
`unknown, detected` and returned as a timeline record. The method does not
sleep, which lets the caller own scheduling and shutdown behavior.

## Command line

Run the interface as `python3 -m
contrib.deepsignal.config_provenance.cli`. Examples:

```text
python3 -m contrib.deepsignal.config_provenance.cli --store ./history snapshot --who technician --note "initial import" cruise.yaml devices.yaml
python3 -m contrib.deepsignal.config_provenance.cli --store ./history log
python3 -m contrib.deepsignal.config_provenance.cli --store ./history diff VERSION_A VERSION_B
python3 -m contrib.deepsignal.config_provenance.cli --store ./history drift --baseline BASELINE_VERSION current.yaml
```

Snapshots contain the parsed configuration rather than comments. The raw
source files are never modified. Missing files and invalid YAML are reported
as errors rather than guessed or replaced.

## Optional Git export

For shore-side review, an operator may copy the store into a Git repository.
Git is not used by the module and is not needed aboard the vessel.
