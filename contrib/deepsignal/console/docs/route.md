# Route tile

The route tile shows the bridge and science watch the next station, the distance left along the route, and arrival times at the current speed over ground.

Add the tile to a console page, using your ship's navigation field names. For example, save this as a page in the console's pages directory.

```yaml
title: Stations
tiles:
  - type: route
    label: Science stations
    wide: true
    route: routes.json
    lat: S330Latitude
    lon: S330Longitude
    cog: S330CourseTrue
    sog: S330SpeedKt
```

Put the following in `routes.json` beside the served console's `index.html`. You can omit the `route` setting when using this file name. Positions are decimal degrees, course is degrees true and speed is knots.

```json
[
  {"name": "Depart", "lat": 32.418, "lon": -118.062},
  {"name": "Station A", "lat": 32.418, "lon": -118.0},
  {"name": "Station B", "lat": 32.45, "lon": -118.0}
]
```

A GeoJSON LineString also works, either on its own or as a Feature geometry. Its coordinates are ordered longitude, latitude. Those waypoints are named Waypoint 1, Waypoint 2 and so on.

Open the Stations page with a live or replayed navigation feed. At the example departure position, Station A becomes active. Its bearing reads about 90° true. Each bearing points directly from the ship to the named destination. The route-end distance and UTC ETA include every remaining leg. Cross-track distance shows which side of the current leg the ship is on. It starts after the first waypoint is reached.

Within 0.1 nautical miles of the active waypoint the tile advances, even if the ship subsequently turns back. The final arrival shows “Route complete”. Reload the console to restart the route or read a changed file.

“Check waypoint” appears after 60 continuous seconds with course over ground more than 45° from the bearing to the active waypoint. It clears when the course returns within 45°. A stale position shows its age and suspends arrival checks and ETAs. Speed below 0.5 knots also suppresses both ETAs.

This tile displays navigation estimates. Chart overlays, steering commands, and allowance for station work are outside its scope.
