# Unified event timeline

`EventTimeline` collects operational and science evidence in one append-only
JSONL file. Each line contains `t`, `kind`, `source`, `subject`, `summary`,
`ref`, and a stable `id`. The ID is the SHA-256 digest of source plus reference,
so polling a source again does not duplicate events.

Configure `EventTimelineTransform` with a writable `path`. Its `transform`
method observes CDS `stderr:logger:*` and `status:logger_status` changes and
returns every input unchanged, including `None`, dictionaries, DASRecords, and
lists. Use `read_jsonl(path, source, kind)` for transition, history, instrument
initialization, EEZ, and maintenance-fix logs. Missing or stale files are not
silently interpreted: callers decide when to read, and normal file errors show
the unavailable source.

`ingest_sealog` accepts events obtained elsewhere. `fetch_sealog` performs only
an authenticated GET and reads its token from the named environment variable.
`note(text, who)` records an operator note. `query`, `around`, and `digest`
provide chronological search, ranked nearby context, and daily JSON plus plain
text output. `around` gives configuration changes and transitions first.

Example configuration is in `contrib/deepsignal/configs/timeline_default.yaml`.
No YAML is loaded by this module. Applications that load configuration must use
`yaml.safe_load`.
