# Sound-speed profile manager

## Turn it on in 5 minutes

The manager reads a completed cast, prepares a local profile for the multibeam operator and advises the watch when another cast is due.

1. From the OpenRVDAS repository root, with its normal Python environment active, run the demo below. It reads the supplied Sea-Bird example, selects a separate example reference cast and prints records to the terminal.
2. Look for `SVM_NewCast: 1`, cast ID `ctd017` and the advice text. Missing live feeds in the demo are expected. For the watch, copy the YAML, point `drop_dir` at the local incoming cast folder, set `pattern` to `'*'`, and attach the monitor to the ship's timestamped navigation, depth and surface records. Use a separate local export directory.
3. Set `profile` to the receipt for the cast the operator selected, or replace that setting with `export_dir` to follow the latest completed local export. An export is not confirmation of a sonar load. Stop the demo with Ctrl-C. To disable it on watch, stop its logger or remove the monitor from the configuration.

```sh
python3 logger/listener/listen.py --config_file contrib/deepsignal/configs/sv_manager_demo.yaml
```

## From cast to SIS

Drop a **completed** file into the incoming folder, preferably by renaming it into place. Keep the original file. The reader announces each new or changed file once per run, including files present at startup. Check the cast ID, UTC time, position, deepest measured depth, removed samples, extension and thinning error before exporting.

From the repository root, run the following with the demo file. For a real cast, substitute its path and the same measured inputs in both commands. Use an existing local export folder that is separate from incoming casts. The example makes one for this demo.

```sh
CAST=contrib/deepsignal/test/sv_manager/fixtures/ctd017.cnv
python3 -m contrib.deepsignal.sv_manager review "$CAST"
mkdir -p ./svp-exports
python3 -m contrib.deepsignal.sv_manager export "$CAST" --fmt asvp --out-dir ./svp-exports
```

For a regional reference add `--climatology local-ocean.csv`. For a missing surface sample, pass the latest known good `--probe-sv` or `--tsg-sv` in m/s. The thermosalinograph (TSG) is the fallback. Check its time and units first. A cast that starts above zero depth stays incomplete until a measured surface speed is supplied. This also applies when the first sample is within 3 m of the surface.

**Verify the ASVP on your ship's SIS before relying on it.** Load the file in the pilot ship's offline tools or Seafloor Information System (SIS) and check the time, coordinates, first and last depths, point count and shape. Confirm the actual limit on that version of SIS or K-Controller. The operator selects and loads the approved file. Keep the file and its adjacent `.json` together. Selecting the receipt in the watch config identifies the cast to monitor.

The manager reads local files and records. It does not connect to ship systems, load a profile or change a setting. There is no UHDAS export. Ocean Surveyor phased-array velocities need only transducer sound speed, which #145 checks.

## What triggers advice

| Watch field | Meaning and default trigger |
| --- | --- |
| `SVM_Age_h` | Hours since the cast, using record UTC. Over 12 h advises a new cast. |
| `SVM_Distance_km` | Great-circle distance from cast to ship, in kilometres. Over 50 km advises a cast. |
| `SVM_SurfaceDiff_ms` | Absolute difference in m/s between the profile at 0 m and the fresh probe, or TSG. Over 2 m/s sustained for 10 minutes advises a cast. |
| `SVM_Quality` | Active profile quality from 0 to 1. The receipt gives the reasons. This is a processing score, not an uncertainty estimate. |
| `SVM_CastAdvice`, `SVM_CastAdviceText` | 1 means action advised. Text names all active triggers and the last cast. An active `SV_Alarm` also triggers advice. So does water deeper than the measured cast endpoint when climatology supplies the extension. |

A missing active cast prompts the watch to select one. A missing measurement leaves its diagnostic null. Read the status text even when advice is 0. It lists missing, invalid and expired inputs. Inspect the named feed and take a cast when conditions warrant. The monitor caches asynchronous samples against **record time**. An expired surface observation breaks persistence. A backward timestamp starts a new observation interval. Pin one receipt for deterministic replay.

For `SVMonitorTransform`, the default limits are `age_h: 12`, `distance_km: 50`, `surface_ms: 2`, `duration_s: 600` and `max_gap_s: 120` (input freshness in seconds). Use positive numbers. In `fields`, the default role names are `lat: Latitude`, `lon: Longitude`, `depth: WaterDepth`, `probe: SV_Probe`, `tsg: SV_TSG`, `alarm: SV_Alarm`. Depth is in metres and coordinates are signed degrees. The demo shows alternative probe and TSG names. The alarm accepts 0 or 1. Set either `profile` (receipt, cast file or Python Profile) or `export_dir`; both default to unset. A pinned raw cast is cleaned with default parameters.

For `SVManagerReader`, `drop_dir` is required. `pattern` defaults to `*` and `follow` defaults to false for a single scan through EOF. Use true with a positive listener interval on watch. Supported extensions are .cnv, .edf, .csv, .svp, .mvp and .txt, case insensitive. `mapping`, `surface_salinity` and `salinity_profile` default to unset. A failed cast logs its filename and retries. Correct the export and drop it again. Use the directory for incoming casts only.

## Input files and processing

* Sea-Bird Seasave CNV uses numbered column definitions and the missing-value flag. NMEA date, time and position come from the header. EDF uses named fields or a depth/temperature heading. Date and time are UTC. An expendable bathythermograph (XBT) measures temperature only. When #112 is installed, select either a measured constant `--surface-salinity` in PSU or a local `--salinity-profile` CSV with increasing `depth_m,s_psu` for linear interpolation. Uncovered or unsupported samples have missing speed. Without conversion, the cast stays available as temperature-only.
* For Valeport, AML, moving vessel profiler (MVP) and other delimited exports, match the header and units against [sondes.yaml](../sv_manager/formats/sondes.yaml). For another format, copy the mapping, edit the delimiter and aliases, and select it with `mapping` or `--mapping`. A CSV can start with lines such as `# time: 2026-11-18T00:00:00Z`, `# lat: 33.2` and `# lon: -118.9`. Coordinates may also be degrees and minutes with a hemisphere. Pressure is retained in dbar; a depth column in metres is required. Files are UTF-8 text, at most 8 MiB and 100,000 sample rows.
* Cleaning takes successive new maximum depths, removes missing speeds and speeds outside 1400 through 1650 m/s, then removes jumps exceeding `--spike-ms 5` from the last accepted sample within `--spike-dz-m 1`. Each depth bin keeps its first observation, and the deepest accepted sample is always retained. The three `--bin-m` widths default to 1, 5 and 25 m, with boundaries at 100 and 1000 m. Filling the surface changes only depth and speed.
* Extension uses 25 m spacing to 12000 m. A local climatology CSV must cover the measured endpoint through 12000 m and name `depth_m,sv_ms`. Its knots are retained before thinning. At depth z the speed is interpolated climatology plus the cast-minus-climatology offset at the join, times exp(−distance below join / taper). `--taper-m` defaults to 200 m.
* Without climatology, the deepest observed slope continues to `--pressure-depth-m` (default 1000 m). Below that, speed increases by 0.017 m/s per metre. A cast already deeper than the switch uses the pressure slope immediately. One measured point cannot determine a gradient. If extrapolation gives a switch speed outside 1400 to 1750 m/s, supply climatology. The 1000 m switch is a configurable approximation.
* Quality begins at 1 for a usable cast and 0 for temperature-only data. After screening it is multiplied by the fraction of accepted samples among accepted plus invalid samples, by 0.9 for missing surface speed and by 0.7 for gradient extension. Reversals and binning do not count as invalid samples. Every stage records its parameters.
* Thinning keeps surface, measured join and bottom, splitting the segment with the largest vertical error first. `--max-points` defaults to 1000. The error in m/s is the maximum absolute difference between the two piecewise-linear profiles before file rounding. Between consecutive input depths the difference is linear, so its maximum absolute value occurs at an input depth.

## Export and replay

ASVP records UTC to the minute and signed decimal coordinates. CSV has `depth_m,sv_ms` columns. Export depths use 0.01 m and speeds 0.001 m/s. Template export uses `--fmt template --template sample.tpl`. Copy a known-good local example and insert `$rows` once. Use `$utc`, `$cast_id`, `$lat`, `$lon` or `$count` in the header. To set row formatting, start the file with a line such as `@row $depth_m,$sv_ms`. Otherwise rows are space separated. Missing header values render empty. Check the result in the receiving program.

The JSON receipt stores the full-precision profile, quality reasons, processing history and SHA-256 hashes of input, references, mapping, output and profile as applicable. Exports are named by cast and receipt digest. Re-exporting identical content selects it again. The manager verifies existing content before reuse. Only a published receipt selects an export. Inspect both files if a hash check fails.

For shore replay, keep the inputs at the recorded paths and use the same module revision. With a receipt you trust, call `load_export(receipt)` from `contrib.deepsignal.sv_manager.files`, then `replay(profile.history)`. Replay repeats ingest, cleaning, extension and thinning and checks each step against the receipt. The hashes detect changed files. Keep the original cast, mapping, references and template with the cruise archive.
