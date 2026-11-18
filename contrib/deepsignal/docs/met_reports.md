# Meteorological report writers

`ReportWriter` turns Python records into period files without MetAcq. Configure it with `class:
ReportWriter`, `module: contrib.deepsignal.met_reports.report_writer`, a template, output `directory`, and
`ship`; see the two `configs/met_reports_*.yaml` fragments. Input may be a `DASRecord`, a dictionary with
`timestamp` and `fields`, a list of either, or `None`. UTC record time—not the computer clock—selects and
closes each 1-minute, hourly, or daily file. Missing values use explicit template text and are never zero.
The SAMOS daily text is zipped after its day closes.

## Adding and verifying a template

Add safe YAML under `met_reports/templates`. Required settings are `name`, `status`, `period`, `filename`,
`row`, `fields`, and `missing`; `header` is optional. Format rows use only Python `str.format_map`
placeholders such as `{air_temperature:.1f}`. There is no expression evaluation. Declare every row field
and missing representation. Use `zip: true` if a closed text file must become a `.txt.zip` archive.

A template with a `parse.pattern` regular expression can be checked against a hand-obtained sample:

```sh
python -m contrib.deepsignal.met_reports verify TEMPLATE SAMPLE
```

The command parses the sample's own named values, renders the row, prints a byte diff, and succeeds only
for an exact match. `samos_daily.yaml` is **VERIFIED-STRUCTURE** against the included NOAA procedure line;
its table-versus-sample field spellings still need confirmation. Defaults follow the table (`RELH`, `TSGWT`,
`TSGS`); pass `designators` to select sample spellings (`RELHUM`, `TSGTEMP`, `TSGSAL`). `noaa_hourly.yaml`
is **UNVERIFIED**: a complete real FM-13 message and exact group encoding citations were unavailable, so
its groups remain `TODO(sample)`. SHIPTRACK, OPSUM, and PCO2 are intentionally absent for lack of specs.

## Usability checklist

* **Discoverability:** example configs name the class, module, templates, and output location.
* **Safe defaults:** SAMOS uses documented table spellings; UNVERIFIED templates warn once on creation.
* **Validation/recovery:** each configuration error is one line naming the setting, observed value,
  expectation, and example; correct the YAML and restart the writer.
* **Visibility/trust:** status is in YAML and documentation; missing data remains visibly missing.
* **Operator effort:** templates are YAML and verification is one command; no code or browser is needed.
* **Accessibility/localization:** N/A—this module writes machine exchange formats with fixed vocabulary.
* **Destructive actions/confirmation:** N/A—only new report files are written; inputs are not modified.
* **Progress/cancellation:** N/A—writes are synchronous per record and have no long-running UI action.
