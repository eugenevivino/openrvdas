# Brief: deepsignal-console-charts

- Decision: D-CONSOLE1 (approved 2026-11-18 05:33Z). Risk tier: medium
- Module: console-charts. Branch `deepsignal/console-charts` from reviewed console-core head
- Mac scratch: `/private/tmp/deepsignal/console-charts/`. Lane: mac, `gpt-6.2-sol` high; review `gpt-6.2-astra` high
- Depends on: console-core only

## Goal
The science watch sees underway strip charts where missing data shows as a gap, never a smooth line.

## Build
- `chart` tile on uPlot: window (minutes or hours), auto y-range with 12% margin, min/max labels, theme tokens read at draw time and on mode change, gap when spacing > 3x the median interval, "NO DATA" label after the last point when the field is stale.
- Holds up to 6 h at 1 Hz per field without the page slowing (budget: under 16 ms per redraw for 4 charts, measured in test).
- `pages/science.yaml` preset (SST, salinity, fluorescence, depth) per mockup, without the map and event log (later modules).

## Failing tests first
`src/tiles/chart.test.ts` (gap insertion, stale label, redraw on mode change), performance test with 21,600 points x 4.

## Acceptance, scope, trust, banned, report, stop
As console-core. Scope: `src/tiles/chart*`, `pages/science.yaml`, tests. Impeccable audit required. Under 30 lines.
