# Shore snapshot writer

`ShoreSnapshotWriter` creates a small, current status card for transfer over a slow
ship-to-shore link. It writes files only; it does not open a network connection. Use rsync or an
OpenRVDAS network writer to transport the resulting files.

## Logger configuration

```yaml
writers:
  shore_snapshot:
    class: ShoreSnapshotWriter
    module: contrib.deepsignal.shore_snapshot.shore_snapshot_writer
    kwargs:
      ship: R/V Example
      out_dir: /var/lib/openrvdas/shore
      period_s: 60
      max_bytes: 4096
      fields:
        - {name: air_temp, label: Air temp, units: degC, decimals: 1}
        - {name: wind_speed, label: Wind speed, units: m/s, decimals: 1}
```

Each record may be a `DASRecord`, a mapping containing `timestamp` and `fields`, a list of either,
or `None`. The writer retains the newest received value and time for each configured field. A
`<name>_QC` value on the input becomes `q`. Missing values stay missing. At each record-time period
boundary, temporary files are completely written and renamed to `snapshot.json` and `snapshot.svg`.
Existing snapshots therefore remain readable until their replacements are complete.

If JSON would exceed `max_bytes`, fields are removed from the end of the configured list and
`truncated` reports the count removed. The SVG calls a value `STALE` when its age is greater than
three periods. Labels, units, values, ship name, and time are HTML-escaped; the SVG contains no
scripts or external references.

## Example output

`snapshot.json` (shown expanded here; the file itself has no extra whitespace):

```json
{"ship":"R/V Example","time":1735689600,"fields":[{"n":"air_temp","v":21.4,"u":"degC","age_s":12,"q":1},{"n":"wind_speed","v":null,"u":"m/s","age_s":null,"q":null}]}
```

`snapshot.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="640" height="124" viewBox="0 0 640 124"><rect width="640" height="100%" fill="#17212b"/><g fill="#f4f7fa" font-family="sans-serif" font-size="16"><text x="20" y="28" font-size="20">R/V Example</text><text x="20" y="52">1735689600</text><text x="20" y="76">Air temp 21.4 degC, 12 s</text><text x="20" y="100">Wind speed missing m/s, missing</text></g></svg>
```

The output directory must be writable by the logger process. Publish it through an authenticated,
least-privilege transfer configured outside this writer. Avoid sensitive field names or ship names
when the shore destination is public.
