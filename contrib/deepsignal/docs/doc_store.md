# Instrument document store

The DeepSignal document store keeps manuals, calibration certificates, photos,
and other files beneath an instrument identifier. Its `index.yaml` records each
file's SHA-256 checksum and size. The only integration with instrument history
is the documented YAML shape; this package does not import history code.

## Commands

Add copies the source and leaves the original untouched:

```sh
python -m contrib.deepsignal.doc_store add ./documents ./certificate.pdf \
  --instrument tsg1 --kind calibration_certificate --cal-id CAL-2026-01 \
  --title "2026 calibration"
```

Use `list ROOT [--instrument ID]` to find documents, `verify ROOT` to report
missing, changed, or unindexed files, and `crosscheck ROOT HISTORY.yaml` to
compare certificate calibration IDs with instrument history. A clean command
returns 0, findings return 1, and invalid command syntax returns 2.

The history file must contain `instruments`, each with `id` and an `events`
list. Calibration events use `type: calibration`, `cal_id`, and `certificate`.
All index paths must be relative to the store and may not contain `..`.
