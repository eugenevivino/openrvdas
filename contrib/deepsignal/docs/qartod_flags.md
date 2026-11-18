# QARTOD flags

QartodFlagTransform adds a quality flag beside each selected sensor reading while preserving
every original value and timestamp.

## Turn it on in 5 minutes

1. Open `contrib/deepsignal/configs/qartod_flags_logger.yaml` and check its `file_spec`.
   In a contrib checkout, keep `test/NBP1406/mwx1`. In a current core checkout, use
   `test/NBP1406/data/mwx1` in its place. From the top of the checkout, run the sample
   using the same Python environment you use for your logger.

   ```sh
   python logger/listener/listen.py --config_file contrib/deepsignal/configs/qartod_flags_logger.yaml
   ```

   Look for `MwxAirTemp_QC` and `MwxAirRelHumid_QC` in the printed records alongside their
   sensor values. The first few temperatures should have a spike flag of 2 while the logger
   collects enough prior readings.
2. Copy the `QartodFlagTransform` entry to your own logger after the parse step and before any
   step that turns the records into text. Change `fields` to the names from your parser and
   set limits in the sensor's units. If your parser can output text or parsed records, choose
   parsed records.
3. Load that logger configuration and check a few records for both the original fields and
   the new flags. To turn flagging off, remove the `QartodFlagTransform` entry and reload the
   logger configuration.

## Flag meanings

| Flag | Meaning | What you may see |
| --- | --- | --- |
| 1 | Pass | At least one check passed and no check found a problem. |
| 2 | Not evaluated | No check ran to completion, for example while the logger collects history. |
| 3 | Suspect | A reading is unusual and deserves a closer look. |
| 4 | Fail | At least one check found a failure, or the value is invalid for a numeric field. |
| 9 | Missing | The field exists but its value is null, NaN or an empty string. |

Missing takes priority. For a numeric value, fail takes priority over suspect, then pass,
then not evaluated. Numeric-looking strings and true/false values fail the syntax check.
A field absent from the record gets no flag. The transform appends new fields in the copied
record. If an input field already uses a reserved flag or reason name, the transform raises
an error before adding flags or updating history. The error names the field in use and
suggests a free `flag_suffix`.

## Settings

Add a test under a field to enable it. A field with an empty test map still gets a flag for
missing or invalid data, and can serve as a companion. Span limits are inclusive and the lower
limit must be less than the upper limit. Decimal and floating-point values use the same exact
decimal comparison at span boundaries. Thresholds and durations must be above zero.

| Setting | What it controls | Default |
| --- | --- | --- |
| `fields` | Map from parsed field names to their checks and optional front check. | Required. |
| `flag_suffix` | Suffix for the overall flag, such as `SeaTemp_QC`. A reason for flag 3 or 4 adds `_reason`. | `_QC` |
| `per_test_flags` | Add individual flags such as `SeaTemp_QC_spike`. A check skipped for a missing or invalid reading shows 2. Timing can still run. | `false` |
| `gross_range.fail_span` | The physically or instrumentally possible range. Values outside it fail. | Required for gross range. |
| `gross_range.suspect_span` | Expected local range. Values outside it but inside the fail span are suspect. | Optional. |
| `climatology.suspect_span` | Expected range for the whole year. Values outside it are suspect. | Supply this or monthly spans. |
| `climatology.months` | A list of entries like `{months: [1, 2], suspect_span: [0, 20]}`. Months are UTC, from 1 to 12. List each month at most once. Months without a span give 2. | Supply this or one year-round span. |
| `spike.suspect`, `spike.fail` | Deviation above either limit from the median of the previous usable readings, in sensor units. Fail must be at least as large as suspect. | Both required for spike. |
| `spike.window` | Number of previous usable readings for the median. | 3 |
| `rate_of_change.max_rate` | Change per second above this limit is suspect. Repeated or backwards time gives 2 for this check. | Required for rate of change. |
| `flat_line.tolerance` | Maximum difference between the highest and lowest readings in a flat-line window, including the current reading. | Required for flat line. |
| `flat_line.suspect_seconds`, `flat_line.fail_seconds` | How long a run must last to be suspect or fail. Fail must be at least as long as suspect. | Both required for flat line. |
| `timing.max_future_seconds` | A timestamp farther ahead of the logger's clock fails. Repeated or backwards timestamps also fail. | 60 seconds |
| `timing.max_gap_seconds` | A gap longer than this since the previous record is suspect. | Optional. |
| `front_check.companions` | Other field names from `fields` that should also move during a front. | Front check is off by default. |
| `front_check.min_change` | Minimum change needed in each companion, in that companion's units. | Required for every named companion. |

Setting `max_rate: 0` under `SeaTemp` produces this message.

```text
Field 'SeaTemp', rate_of_change.max_rate: got 0, expected a finite number greater than zero. Good example: {max_rate: 0.5}.
```

Use a positive limit in the transform's `kwargs`.

```yaml
fields:
  SeaTemp:
    rate_of_change:
      max_rate: 0.5
```

## How to pick thresholds

Use the instrument limits for the fail span and typical readings for the suspect span.
Pick monthly spans using past measurements from the area and season you work in. Set spike
and rate limits by looking at how far and how fast good readings usually move. For flat line,
start with a tolerance near the instrument's resolution and a time long enough that a steady
reading is worth checking. Set the timing gap above the normal interval between records,
allowing for normal delays. Try the limits on a recorded cruise and review flagged readings
before using the flags for alarms.

## Sensor fault or real front?

A sharp temperature jump can be a fault or the ship crossing an ocean front. If a second
field such as salinity moves enough during the same window, the spike or rate check gives 3
and writes `AMBIGUOUS` in the reason field. Check the readings before trusting or discarding
either one.
The spike window starts at the oldest reading used in its median. The rate window starts
at the previous usable reading. In either case the companion needs a previous usable reading
in that window. A missing companion or one that failed a check is skipped, both when
checking the current record and when saving a reading to compare against later. If no other companion
confirms it, the original flag stands and the reason names the jump check and any missing or
bad companions. A companion whose jump is independently corroborated can then confirm another
reading. Two readings that both fail their jump checks need evidence from another companion.
A gross-range, syntax or timing failure still makes the overall flag 4. When a hard failure
and unavailable companions both contribute to the result, the reason starts with the failure.
Evidence that softens one field cannot flow back through that field to soften its source.
The configuration accepts reciprocal companion pairs. A cycle involving three or more
fields produces a configuration error that lists the cycle.

## What it does not do

- It cannot raise a stale-data alarm during silence. The transform runs when a record arrives.
- Its spike check uses earlier readings so it can flag the current reading immediately. The
  centered QARTOD form needs a sample after the current one.
- Flagging leaves all sensor data in place, including records marked fail or missing.
- History is kept in memory for each field, with a limited number of readings for spike and
  rate and a limited time window for flat line. Readings that fail syntax or gross range are
  left out of history. Each flat-line window tracks its minimum and maximum and retains
  the last reading at or before the cutoff to establish the full duration. Restarting the
  logger clears the history and the checks warm up again.
- A record with a missing timestamp keeps its original readings and timestamp. Flat line,
  rate of change and timing report flag 2 (`NOT_EVALUATED`). A missing timestamp clears
  flat-line history, so the next usable reading starts a new window.
- Monthly climatology gives 2 if the timestamp cannot be converted to a UTC month. The
  transform logs this conversion failure at most once per minute.
