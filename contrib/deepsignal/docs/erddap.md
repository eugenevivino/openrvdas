# ERDDAP dataset generator

This module turns a small ship-specific YAML file into an ERDDAP
`EDDTableFromAsciiFiles` fragment. It does not install, start, configure, or ship
the separate ERDDAP Java server. It also does not create, alter, or delete data
files.

## Turn it on in 5 minutes

1. Copy `contrib/deepsignal/configs/erddap_example.yaml` and edit the institution,
   descriptive metadata, dataset IDs, directories, and columns. Dataset IDs may
   contain only letters, digits, and underscores. Each source CSV must have a
   header row and ISO 8601 UTC strings in its configured `time_column`.
2. Check the file:

   ```sh
   python -m contrib.deepsignal.erddap check my_erddap.yaml
   ```

   Each error is printed on its own line. The command returns status 1 for
   errors. If optional CF standard-name vocabulary data from DeepSignal #117 is
   installed under `contrib/deepsignal/vocab/`, unknown `standard_name` values
   are warnings; without that data, this check is silently skipped.
3. Generate the fragment:

   ```sh
   python -m contrib.deepsignal.erddap generate my_erddap.yaml > datasets_fragment.xml
   ```

4. Back up ERDDAP's `datasets.xml`, then paste the generated `<dataset>...</dataset>`
   elements as children of its existing `<erddapDatasets>` root. Do not paste a
   second XML declaration or root element. Follow the ERDDAP deployment's normal
   reload procedure.
5. From the ERDDAP installation directory, use its `DasDds` tool with the new
   dataset ID and confirm that DAS and DDS metadata are generated. Then request
   a small time subset through the ERDDAP tabledap page and compare it with the
   source CSV.

The generator escapes XML values, supplies time and QARTOD flag metadata, and
defaults `license` to `See ship data policy`. It does **not** inspect the CSV,
guess units or metadata, validate that paths exist on the ERDDAP host, perform
quality control, or verify the fragment against a running ERDDAP. A real ERDDAP
load remains a deployment check.
