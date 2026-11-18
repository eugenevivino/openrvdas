# Brief: deepsignal-console-bridge

- Decision: D-CONSOLE1 (approved 2026-11-18 05:33Z). Risk tier: medium
- Module: console-bridge. Branch `deepsignal/console-bridge`, based on `deepsignal/console-core` head after its review passes
- Mac scratch: `/private/tmp/deepsignal/console-bridge/`. Lane: mac, `gpt-6.2-sol` high; review `gpt-6.2-astra` high (wind angles are math)
- Depends on: console-core; reads output fields of the vector-wind module (`deepsignal/vector-wind`) when present

## Goal
The bridge sees wind, heading, speed, depth, barometer trend, temps and position at a glance, day or night.

## Build
- `wind_dial` tile per mockup: true wind speed and direction, relative to bow (port/starboard), North up / Ship up toggle remembered per screen, 30 min speed sparkline.
- Relative angle math in one pure function, tested at 0, 180, 359/1 wraparound, port vs starboard.
- `number` tile gains `trend: <minutes>` (rising/falling/steady with value per period) and `compass: true` (NNW etc.).
- `pages/bridge.yaml` preset matching the mockup Bridge page; field names taken from the sample config.

## Failing tests first
`src/tiles/windDial.test.ts` (angles, toggle), `src/tiles/trend.test.ts`, extend `test_console_live.py` with a Bridge page load in Night mode asserting no pixel with G or B > 0.15*R in a screenshot.

## Acceptance, scope, trust, banned, report, stop
As console-core. Scope: `contrib/deepsignal/console/src/tiles/**`, `pages/bridge.yaml`, tests. Impeccable audit required. Under 30 lines.
