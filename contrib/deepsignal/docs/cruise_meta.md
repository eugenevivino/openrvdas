# Cruise metadata

The cruise metadata module keeps the cruise identifier, ship, dates, ports and people in one checked
YAML file. The console, archive jobs and download tools can all use that file instead of repeating
those values in separate configurations.

Copy `contrib/deepsignal/configs/cruise_meta_example.yaml` and edit it for the cruise. Participants
must contain names only when those people have agreed to be listed. Do not put email addresses or
phone numbers anywhere in this file.

## Check and inspect a file

```console
python -m contrib.deepsignal.cruise_meta check cruise.yaml
python -m contrib.deepsignal.cruise_meta show cruise.yaml
```

`check` prints one plain error explaining the setting and expected form when validation fails. A
valid file prints `OK`. `show` validates first and then prints the normalized YAML representation.

## Reader configuration

OpenRVDAS can load the reader using its standard `class` and `module` settings:

```yaml
class: CruiseMetaReader
module: contrib.deepsignal.cruise_meta.reader
path: cruise.yaml
interval: 60
```

Every interval, the reader emits `cruise_id`, the 1-based `cruise_day`, and `cruise_active`. The
active interval includes both the start and end instants. Times after the end retain their actual
cruise day rather than being clamped or guessed.

The optional `data_policy` path is recorded for consumers but is not loaded by this module. UN/LOCODE
values use two letters followed by three letters or digits. This module has no dependency on another
DeepSignal module.
