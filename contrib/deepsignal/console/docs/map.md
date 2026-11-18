# Offline ship track map

The map tile shows where the ship has been and can color that track by an underway measurement without contacting the internet.

## Configure it

Add a tile like this to a console page:

```yaml
- type: map
  label: Ship track
  lat: S330Latitude
  lon: S330Longitude
  window: 2 h
  color_by: TsgTemp
  heading: S330HeadingTrue
  events: [event:log]
  tiles: tiles/{z}/{x}/{y}.png
  zoom: auto
  wide: true
```

Omit `tiles` for the built-in latitude/longitude graticule. To prepare an offline tile folder from an MBTiles file, install the common `mb-util` tool on a shore computer and run `mb-util survey.mbtiles tiles`; copy the resulting `tiles/` directory next to the deployed console bundle. The browser makes no internet tile requests.

## Check it

Open the page while position data is arriving. The track should grow, the ship marker should follow its end, and tapping the track should show UTC time, position, value, quality, and freshness. Temporarily stop position data to confirm the hollow **Position stale** marker and age appear.

## Limits

This tile does not download maps, navigate the ship, choose or create page presets, edit MBTiles files, or preserve a track beyond the history retained by the console store. Missing raster tiles remain as the token-colored background.
