# Seismic shot QC

This passive module checks each parsed gun-controller shot record. It reports gun timing errors,
missing shot numbers, interval and spacing departures, record-clock offset, and navigation quality.
It never opens a socket, sends data, or changes a gun, streamer, or navigation setting.

## Capture and mapping

Capture the controller's ASCII output with an existing OpenRVDAS serial or UDP reader. Copy
`configs/seismic_shotlog_template.yaml`, then replace its invented example format with the ship's
captured format and map the resulting fields into `ShotQCTransform` keyword roles. The template is
not a Real Time Systems, Seamap, Sercel, Digibird, GeoEel, or other vendor specification.

Fire time may be finite UNIX seconds or a time-of-day string. For time of day, configure
`date_source`; otherwise the UTC date of the record timestamp is used. Missing and non-finite input
stays missing. Position is linearly interpolated only between fixes that bracket fire time and are
within `nav_max_gap_s`. It is never extrapolated. History is limited to the latest 120 seconds.

Spacing uses the haversine formula and fixed mean Earth radius 6,371,008.8 m, so it is approximate.
Alarms assert on a bad shot and clear after three consecutive good shots, using record order and
timestamps rather than wall-clock time.

## Shot navigation output

`P111Writer` creates one CSV file per configured line. Its header identifies WGS 84, degree and UTC
units, and the configured ship name. Each data row contains shot number, UTC fire time, latitude,
and longitude. This is only the public-format subset described here, not a claim of full IOGP P1/11
conformance. The file says **P1/11 subset, verify with the processing team before delivery**.
