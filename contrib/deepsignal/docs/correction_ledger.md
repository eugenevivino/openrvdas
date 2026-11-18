# Correction ledger

Use the ledger to publish a sensor correction alongside the original reading.
Each proposal carries its method, evidence, uncertainty, and author. An
independent reviewer can approve it, reject it, or later roll back an approval.
The correction ID on each output leads back to that proposal and its review
events.

## Turn it on in 5 minutes

From the repo root with the normal OpenRVDAS listener dependencies available, run:

```sh
listen --config_file contrib/deepsignal/configs/correction_apply_logger.yaml
```

In this checkout, you can also invoke the listener as
`python3.12 logger/listener/listen.py --config_file contrib/deepsignal/configs/correction_apply_logger.yaml`.

The sample replays NBP1406 thermosalinograph data. The first five readings carry
`TSG1Temp_corr`, `TSG1Temp_corr_id`, and `TSG1Temp_corr_u` alongside
`TSG1Temp`. A second offset for the next ten seconds was rolled back, so those
readings carry only the original fields. The sample offsets are illustrative.

Inspect the sample ledger or create your own using the CLI:

```sh
python3.12 -m contrib.deepsignal.corrections list \
  --ledger contrib/deepsignal/configs/correction_apply_ledger.jsonl
python3.12 -m contrib.deepsignal.corrections verify \
  --ledger contrib/deepsignal/configs/correction_apply_ledger.jsonl

id=$(python3.12 -m contrib.deepsignal.corrections propose \
  --ledger my-corrections.jsonl --author ana --field TSG1Temp \
  --start 2014-08-01T00:00:00Z --end 2014-08-01T00:00:10Z \
  --method offset --value 0.1 --standard-uncertainty 0.02 \
  --evidence cal-report.txt --code-version v1 --reason 'Bench calibration' \
  --correction-state CORRECTABLE --model-id C1 \
  --fit-refs fit-01 --validation-refs check-02)

python3.12 -m contrib.deepsignal.corrections approve "$id" \
  --ledger my-corrections.jsonl --by bo --reason 'Reviewed against check-02'
```

Use the same ID syntax with `reject` for a pending proposal and `rollback`
for an approved proposal. Point the transform's `ledger_path` at your ledger
and set `fields` to the field names in your logger.

## Ledger format contract

The ledger is a UTF-8 JSON Lines file with one object per line and a newline
after every event. Every object has `event`, `id`, `prev_hash`, and `hash`.
The first event has JSON `null` for `prev_hash`. Every later event uses the
previous event's `hash`. Each `hash` is the lowercase SHA-256 hex digest of
the whole event object with only `hash` omitted, including `prev_hash`.
The canonical bytes are the UTF-8 encoding of Python
`json.dumps(event_without_hash, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)`.
The trailing newline is outside the digest.

Use `Ledger.append(path, event)` from `contrib.deepsignal.corrections` to
append a new event. Supply the event fields below and the two hashes are
generated under a file lock. Always append through this API or the CLI so that
writers share the lock. `Ledger.load(path)` verifies the chain, validates every
event, and replays the transitions. A failed line names its line number.
`Ledger.active(field, t)` queries the verified snapshot for current approvals
covering `t`.

### Propose event

Set `event` to `propose` and `id` to a unique UUID4 in lowercase,
hyphenated form. The initial status is `proposed`. Put method parameters at
the top level of the object.

| Field | Value |
| --- | --- |
| `field` | Field name in an OpenRVDAS record |
| `instrument` | Optional instrument history ID, kept as provenance. Matching uses the field and time. |
| `start`, `end` | UTC ISO timestamps with `Z` or `+00:00`, optionally with up to six fractional digits. The interval includes `start` and excludes `end`. |
| `method` | Method name from the table below |
| `standard_uncertainty` | Finite, nonnegative standard uncertainty in the field's units. On load, `uncertainty` is accepted in its place. |
| `coverage_interval` | Optional two-element array `[low, high]` of finite numbers in the field's units, with low at most high |
| `evidence` | One or more free-text references or file paths |
| `author`, `code_version`, `reason` | Nonempty text identifying the proposer, the producing code, and why the correction was proposed |
| `correction_state` | Must be `CORRECTABLE` |
| `model_id` | One of `C0`, `C1`, `C2`, `C3`, `C4`, `C5` |
| `fit_refs`, `validation_refs` | Arrays of reference IDs. The arrays may be empty and must have no IDs in common. |
| `independence_score` | Optional finite number from 0 through 1 |

All method parameters that represent numbers must be finite.

| Method | Parameters | Result |
| --- | --- | --- |
| `offset` | `value` | `raw + value` |
| `linear_drift` | `rate_per_day`, UTC ISO timestamp `t0` | `raw + rate_per_day * (timestamp - t0) / 86400`, using elapsed seconds |
| `polynomial` | Nonempty `coefficients` array, lowest order first | `coefficients[0] + coefficients[1] * raw + coefficients[2] * raw**2 + ...` |
| `time_shift` | `seconds` | Copies the raw value into `<field>_corr` and puts the shifted Unix timestamp in `<field>_corr_time` |
| `gain_offset` | `offset`, nonzero `gain` | `(raw - offset) / gain` |

### Review events and approval rule

An `approve`, `reject`, or `rollback` event carries the proposal `id`,
a reviewer identity in `by`, a nonempty `reason`, and a UTC ISO `time`.
Only a proposed entry can be approved or rejected. Only an approved entry
can be rolled back. The reviewer and author must differ, ignoring letter
case and surrounding whitespace. Review timestamps are audit metadata.
Status follows ledger order and applies to the entire proposal interval,
including when replaying historical data.

The recorded names provide attribution. Keep the ledger under access
controls appropriate for your reviewers. The hash chain detects inconsistent
event content or links. Authentication of reviewer identities and detection
of a fully rehashed or truncated file at startup require an external trust
mechanism.

## Applying corrections

With one active entry for a configured field at the record timestamp, the
transform adds `<field>_corr`, `<field>_corr_id`, and `<field>_corr_u`.
It adds `<field>_corr_time` for `time_shift` only. Record timestamps can be
Unix seconds or UTC ISO strings. The ledger is reloaded when the file changes.
Reload verifies the chain and requires the previously verified history to be
present. An invalid ledger raises an error. Multiple active entries for a field
suppress the correction and log a warning once per overlapping pair. A human
resolves overlaps through review events. Existing output names are preserved
and cause that correction to be skipped.

## What it does not do

The ledger never overwrites raw fields or record timestamps and never
auto-approves a proposal. Rollback changes subsequent transform results,
including replays. Previously exported records retain their correction IDs
and values.
