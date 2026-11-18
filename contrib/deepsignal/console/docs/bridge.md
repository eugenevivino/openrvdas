# Bridge console module

The Bridge page puts true wind, navigation, depth, weather, sea temperature, and position on one no-scroll watchkeeping display.

## Turn it on

The module supplies a preset named `bridge`. Include it in the console page list:

```yaml
pages: [bridge]
```

To configure the wind dial on a ship page, use exact CachedDataServer field names:

```yaml
- type: wind-dial
  label: True wind
  speed: Avg1mPortTrueWindSpeed
  direction: Avg1mPortTrueWindDir
  speed_fallback: PortTrueWindSpeed
  direction_fallback: PortTrueWindDir
  heading: S330HeadingTrue
  gust: Avg1mPortTrueWindSpeedMax
  unit: kn
  average_label: 1 min vector mean
```

Open **Bridge** and confirm that the wind arrow, ship outline, numeric wind, heading, course, speed, and supporting values update. Use **North up** to keep north at the top or **Ship up** to keep the bow at the top; that choice is retained for this screen.

The module does not calculate true wind, average samples, substitute missing average windows, or correct sensor data. Those values must be published by OpenRVDAS. It also does not use an old heading for relative-to-bow wind: a stale or missing heading is stated beside an em dash.
