# DeepSignal Console plugin contract

Version 1, 2026-11-18. Types: `src/contract/index.ts`. Test feed: `src/contract/fake-feed.json`.
Owned by console-core. Module tasks build against this and never edit it. A change
here is a decision for the lead, not a task.

## 1. One module, one folder
Each feature lives in `src/modules/<id>/` and its `index.ts` default-exports a
`ConsoleModule` (`id` equals the folder name). Core finds every module with
`import.meta.glob('./modules/*/index.ts', { eager: true })` in `src/registry.ts`,
so adding a module never edits a shared file. A module may export any of:
tiles, routes, presets, engines, slots, adapters (see the types).

Your module owns only `src/modules/<id>/**` and `docs/<id>.md`. Tests live
beside the code as `*.test.ts(x)`. Python tests, if any, are
`contrib/deepsignal/test/console/test_<id>*.py`.

## 2. Data store
Core subscribes to the CachedDataServer websocket (default `ws://<host>:8766`)
and keeps one `FieldState` per field. Modules read through `ctx.store` and never
open their own websocket.

- `value`, `sourceTime` (record timestamp), `receiveTime` (console clock).
- Lead-approved additive pilot repair: optional `lastReported` preserves the latest
  observed producer value and timestamp, including rejected reports. It is history,
  never evidence of a new measurement or a healthy current value. QC-only responses
  may leave `sourceTime` absent while this history remains available.
- Freshness, from expected period T (page `period`, else median of the last 20
  intervals): LIVE age <= 2T; AGING 2T to 5T; STALE > 5T (value kept); NO_DATA
  past the hard timeout (60T, at least 300 s): value replaced by "—", `lastGood` kept.
  Learned intervals do not bridge subscription gaps; a gap is not a measured
  change in producer cadence.
- Quality from QARTOD fields published by the QARTOD module: `<field><qc_suffix>`
  (default suffix `_QC`): 1 PASS, 2 NOT_EVALUATED, 3 SUSPECT, 4 FAIL, 9 MISSING;
  absent means NOT_EVALUATED. Per-test flags `<field>_QC_<test>`, text `<field>_QC_reason`.
- Health is UNKNOWN until an adapter calls `store.setHealth({logger}, ...)`.
  Field-to-logger comes from `describe(field).logger` or the page tile `logger:` key.
- The four axes are independent. Never derive one from another (UNKNOWN health is
  not FAIL quality; STALE is not FAIL).

OpenRVDAS status fields (from `server/logger_manager.py`, quoted):
- `status:logger_status`: `{logger_name: {'config': config_name, 'status': status}}`,
  status one of `RUNNING`, `STARTING` (runnable, not running, not given up), `FAILED`,
  `EXITED` (not runnable, e.g. the off config). Sent every manager loop.
- `status:cruise_mode`: `{'active_mode': name}`.
- `stderr:logger:<logger>`: one formatted stderr line per record.

## 3. Pages
Page files are YAML: `title`, optional `order`, `tiles: [ {type, label, wide, ...} ]`.
Built-in pages come from module `presets`; a ship's own files in `public/pages/`
override presets with the same id; `console.yaml` `pages:` sets which show and in
what order (empty = all). Auto-generated pages use `ctx.pages.register()`.
A tile may carry `fallback: <type>`: when its `type` is not installed, core renders
the fallback type with the same settings; without a fallback, core shows a
PageProblem for that tile only and the rest of the page still works.
`TileDef.validate` throws a `PageProblem`; core shows it as:
"<file>, tile <n>: <setting> is <saw>. Expected <expected>. Example: <example>".

## 4. Lighting and tokens
Modes `day`, `dusk`, `night`; night palettes `red` (default) and `neutral`; dim
0.15 to 1.0; stored per screen. Core paints CSS custom properties on `:root`;
modules use only these, never literal colors:
`--bg --panel --panel2 --line --fg --muted --accent --ok --check --stale --down
--chart --grid --scroll-thumb` and fonts `--f-number --f-body --f-mono`.
Canvas and SVG read tokens with `getComputedStyle` at draw time and redraw on
`ctx.lighting.subscribe`. Values per mode: `DESIGN.md`. Night red: every pixel
G and B <= 0.15 R. No module may paint a light surface in Night, including empty,
loading and error states.

## 5. Alerts
`ctx.alerts.raise()` with tier A1 to A4, plain `title`, `source`, `consequence`,
`firstAction`, `since`. One root cause, one alert: use `groupKey`. No audio.
Flashing only for an unacknowledged A1.

## 6. Time
Modules use `ctx.clock.now()` (seconds) only. Tests inject a fake clock and step it.

## 7. Fake feed for tests
`src/contract/fake-feed.json`: `{start_time, fields: {name: FieldDescription},
scenarios: {...}, events: [{t, field, value}]}` with 600 s of synthetic data.
Scenarios: `flr1_fails` (FlrChl stops at t=228, logger FAILED from t=240 with
stderr lines), `knud1_restart` (depth gap 300-329, STARTING then RUNNING),
`tsg_suspect` (TsgTemp_QC 1 to 3 at t=400 with a reason while values stay LIVE),
`wind_avg` (Avg1m wind once a minute, T=60), `rad1_off` (EXITED throughout).
Each module test builds its own minimal fake `ConsoleContext` from this file in
its own folder (a shared test kit arrives with core v2; do not wait for it).
