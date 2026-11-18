# Vessel geometry and lever-arm correction

## Turn it on in 5 minutes

This transform uses the ship's true heading and a measured antenna offset to add the latitude and longitude of the ship's reference point to each satellite navigation fix.

1. **Try the example.** From the OpenRVDAS repository root, use the Python environment that runs your logger. The sample logger reads from the terminal and prints to the terminal. First check its geometry settings, then run one test fix.

   ```sh
   python3 -m contrib.deepsignal.geometry.transform contrib/deepsignal/configs/geometry_logger.yaml
   printf '%s\n' '{"timestamp":100,"fields":{"Latitude":0,"Longitude":0,"Heading":0}}' |
     python3 -m logger.listener.listen --config_file contrib/deepsignal/configs/geometry_logger.yaml
   ```

   Look for `Geometry settings OK.` and two added fields. At heading 0 degrees, the example antenna sits forward and to port of the reference point. The corrected fix moves south and east. Expect `CorrectedLatitude` near -0.000111237 degrees and `CorrectedLongitude` near +0.000009881 degrees. The sample exits after the fix.

2. **Enter your survey.** Copy [the example survey](../configs/geometry_example.yaml) to a ship-specific file named `vessel_geometry.yaml`. Replace the demonstration measurements with the ship's surveyed values. A [blank survey](../geometry/vessel_geometry.yaml) is also available. Give each sensor or survey mark its own ID. Keep the survey date and surveyor with the measurements.

3. **Enable it on one logger.** Copy the `LeverArmTransform` entry from [the sample logger](../configs/geometry_logger.yaml) into your logger's transform list after the position and heading have been decoded into named fields. Set the file path, antenna ID and three field names. Run the settings check from step 1 with your logger file, then reload that logger. Look for both corrected fields alongside the original fix. To turn it off, remove that entry and reload the same logger.

## How to read the survey

All distances are in metres from the same reference point. On the plan view, the bow is at the top. Port is left and starboard is right.

```text
                 bow
                  ^  +x forward
                  |
        port      O------> +y starboard
                  |
                stern

        O = reference point (0, 0, 0)
        +z points up from the deck
```

In `positions`, record the antenna and other sensor locations. In `monuments`, record fixed survey marks. Each entry needs a unique `id` and all three coordinates, including zeroes. The checker rejects duplicate IDs and missing or invalid coordinates. For a sensor over 200 m from the origin in three dimensions it issues a warning. Check the units and the reference point against the survey.

## Logger settings

| Setting | What to enter |
| --- | --- |
| `geometry_file` | Required. Path to the vessel survey, absolute or relative to the logger's working directory. |
| `antenna` | Required. ID of the navigation antenna in `positions`. |
| `lat_field`, `lon_field` | Required. Two separate input field names holding latitude and longitude in decimal degrees. |
| `heading_field` | Required. Field holding true heading in degrees clockwise from north, from 0 to 360. |
| `target` | Defaults to the ship reference point. To use another surveyed point, enter its ID. |
| `heading_timeout` | Maximum heading age in seconds. Default 2. A heading exactly this old is usable. |
| `prefix` | Text before the output names. Default `Corrected`. Choose an unused pair of names. |

The latest heading is kept by record timestamp (seconds on the same clock as the position). A heading can arrive on its own or in the fix. Send both position coordinates together. A future heading is unusable for an earlier fix. A bad new heading makes the cached heading unavailable until a valid one arrives.

## When the corrected fields are missing

The incoming record passes through intact. Check the logger warning. A stale-heading warning gives the fix time, last heading, its time, its age and the allowed age. Check the heading feed and the sensor clocks. For an incomplete fix, check the field names and the position feed. Correction resumes on the next usable fix. If an output name already exists, choose a different prefix and reload the logger. The transform preserves both existing values and record metadata.

The horizontal correction uses the local north and east radii of the WGS84 Earth model. Longitude wraps at 180 degrees. For latitudes beyond 89.5 degrees north or south, the transform passes the fix through with a warning.

Only heading contributes to the correction. Roll and pitch are ignored, as is height correction. The horizontal error from roll alone is about the vertical separation times the sine of the roll angle. For a 25 m mast at 1 degree of roll this is about 0.44 m, under 0.5 m. Pitch produces a similar fore-and-aft error. Larger tilts or simultaneous roll and pitch can exceed 0.5 m.
