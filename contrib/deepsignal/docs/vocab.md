# Standard vocabularies

This module keeps downloaded vocabulary data local and normalizes every source into one JSON format.
It ships no term list and makes no network requests. Download the CF Standard Name Table from the CF
Conventions project; NVS collections L22, L35, EL1, EL2, and C17 from the British Oceanographic Data
Centre's NERC Vocabulary Server; R2R device types from Rolling Deck to Repository; and UN/LOCODE from
the United Nations Economic Commission for Europe.

Import downloaded files from the repository root:

```sh
python -m contrib.deepsignal.vocab import_cf downloads/cf-standard-name-table.xml
python -m contrib.deepsignal.vocab import_nvs downloads/L22.rdf --scheme l22
python -m contrib.deepsignal.vocab import_csv downloads/r2r.csv --scheme r2r_device_types --id-col code --label-col name
python -m contrib.deepsignal.vocab import_csv downloads/locode.csv --scheme un_locode --id-col LOCODE --label-col Name
```

The commands write `cf.json`, `l22.json`, or the requested scheme name beside the package code. Use
`--store DIRECTORY` before the subcommand to select another local store. Re-import a current publisher
file to replace stale data; the JSON records its source, version where supplied, and UTC import time.

A tag file maps each local field to one or more standard identifiers and may state its units:

```yaml
TSG_Temp:
  cf: sea_water_temperature
  units: degree_C
CTD:
  l22: TOOL0001
```

Run `python -m contrib.deepsignal.vocab check tags.yaml` to report absent schemes, unknown terms, and CF
unit mismatches. Kelvin and degrees Celsius are explicitly reported as compatible rather than silently
treated as equal. Search imported labels and definitions with
`python -m contrib.deepsignal.vocab search cf temp`.
