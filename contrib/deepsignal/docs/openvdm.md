# DeepSignal OpenVDM bridge

`QualityDayWriter` writes one CSV row for every field ending in `_QC`. It places files at
`<root>/<data_id>/<data_id>-quality-YYYY-MM-DD.csv`, using the record timestamp's UTC day. Configure the
writer with `contrib/deepsignal/configs/openvdm_quality_writer.yaml`, changing `root` and `data_id` for
the vessel. Existing daily files are appended to and are never rewritten.

## Collection System Transfer

In OpenVDM 2.17, add a Collection System Transfer with these values:

* Name: `DeepSignal`
* Source: `/var/lib/openrvdas/quality/*/*-quality-????-??-??.csv`
* Destination: `DeepSignal/`
* Include: `*-quality-????-??-??.csv`
* Exclude and ignore: leave empty

Use the actual configured writer root if it differs from `/var/lib/openrvdas/quality`. The transfer is
an rsync copy, so the source products remain unchanged.

## Install the Data Dashboard plugin

Run these commands from the OpenVDM checkout, replacing `/path/to/openrvdas` with this checkout:

```sh
cp /path/to/openrvdas/contrib/deepsignal/openvdm/dist/deepsignal_plugin.py.dist \
  server/plugins/deepsignal_plugin.py
cp /path/to/openrvdas/contrib/deepsignal/openvdm/dist/deepsignal_quality_parser.py.dist \
  server/plugins/deepsignal_quality_parser.py
```

Restart OpenVDM after copying. The parser defaults to failure when flag 4 exceeds a 0.01 share and a
warning when flags 3 or 9 exceed a 0.05 share. It reports CSV row validity and time bounds, plus hourly
non-pass flag share series. Validate this installation in a real OpenVDM 2.17 deployment with
`openvdm_sample_data`; that integration is outside this repository's test environment.
