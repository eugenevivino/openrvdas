# Brief: deepsignal-console-core

- Decision: D-CONSOLE1 (Eugene approved modules 1-4, 2026-11-18 05:33Z)
- Risk tier: medium (read-only display; never writes to loggers)
- Module: console-core. Branch `deepsignal/console-core`
- Mac scratch path: `/private/tmp/deepsignal/console-core/` only
- Base: contrib master 3b4b76e (fork branch `deepsignal/console-core` already at it)
- Lane: mac, `gpt-6.2-sol` high. Review: `gpt-6.2-astra` high (separate job)
- Fresh session, under 40 turns
- Upstream home: openrvdas_contrib, folder `contrib/deepsignal/console/`

## Goal
A tech copies one folder onto the ship server and gets a live, readable data console
with Day, Dusk and one-tap Night red modes, fed by the CachedDataServer already running.

## Read first
`contrib/deepsignal/console/DESIGN.md` (copy from desk `design/console-DESIGN.md`),
the mockup HTML (`mockup.html` placed in the scratch dir by the lead), and
`server/cached_data_server.py` (websocket protocol: `fields`, `describe`, `subscribe`
with `fields: {name: {seconds: N}}` and back history, `ready`).

## Stack (fixed; no substitutions)
React 19 + TypeScript + Vite + Tailwind 4 (same as upstream web_frontend), uPlot for
charts (only a sparkline here), Vitest + Testing Library. Fonts as local files.
`node_modules` is installed by the lead before the job (no network in the job).
Built output goes to `contrib/deepsignal/console/dist/` and IS committed (ships need no Node).

## Build exactly this
1. App shell: top bar per DESIGN.md, hash routes `#<page-id>`, keys N and 1-9.
2. Lighting modes per DESIGN.md including the inline boot script (no light flash).
3. `cds` client: one websocket to `ws://<host>:8766` (configurable in `console.yaml`),
   subscribes only to fields used by visible tiles, backfills `history` seconds on load,
   auto-reconnects with backoff, exposes per-field `{value, timestamp}` and a connection
   state. Shows "Reconnecting, last data N s ago" in the live pill; never a frozen screen that looks live.
4. Stale logic: tile is Stale when now - timestamp > `stale_after` (default 30 s).
5. Page file loader: reads `pages/*.yaml` served next to the bundle, validates against
   a schema, and on error shows a plain message naming the file, tile number, setting,
   what it saw, what it expected, and an example (USABILITY 5).
6. Tiles: `number` (label, field, unit, decimals, optional sparkline minutes) only.
7. `console.yaml` + one sample `pages/example.yaml` + sample logger config under
   `contrib/deepsignal/configs/` that runs a CachedDataServer with simulated fields
   from test/NBP1406 data so the console shows live numbers with no ship.
8. README section "Turn it on in 5 minutes" (nginx location block given verbatim, how
   to see it working, how to turn it off) and "What it does not do".

## Failing tests first (paste RED output)
- `src/lighting.test.ts`: night tokens at dim 0.6 and 1.0 all have G,B <= 0.15*R; mode persists; N toggles.
- `src/cds.test.ts` (mock WebSocket): subscribe message shape; reconnect; stale after 30 s.
- `src/pages.test.ts`: bad field name / bad tile type give the plain message format.
- `contrib/deepsignal/test/console/test_console_live.py`: starts a real CachedDataServer
  on a free port, publishes two fields, serves `dist/` and loads it in headless Chromium
  (Playwright); asserts the number tile shows the value, then stops publishing and asserts
  "Stale" appears. Skip with a clear reason only if Playwright is not importable.

## Impeccable (dev only, pinned, telemetry off)
After tests pass: run Impeccable audit and its checker on the built page in all three
modes; fix findings that do not conflict with DESIGN.md; put the report at
`contrib/deepsignal/console/IMPECCABLE-REPORT.md`. Do NOT use live mode or Apply.

## Acceptance (exact commands, from contrib/deepsignal/console)
```
npm run lint && npm run type-check && npm run test && npm run build
```
```
pytest contrib/deepsignal/test/console/ -v
```
```
flake8 contrib/deepsignal/test/console/
```

## Scope
Only `contrib/deepsignal/console/**`, `contrib/deepsignal/test/console/**`,
`contrib/deepsignal/configs/console_*`. Everything else read-only. No core changes.

## Trust boundaries
Page files and websocket data are untrusted: no `eval`, no `innerHTML` with data,
render values as text. Never show an old value as current. No writes to the cache.

## Non-goals and banned
No AI, no editor, no charts beyond sparkline, no map, no auth. No network in the job.
Rules in docs/CODEX.md rule 13 apply. Nothing outside /private/tmp/deepsignal/console-core/.

## Report format
Under 40 lines: files added, test names with RED then GREEN output, bundle size,
Impeccable findings fixed and declined (with reason), USABILITY 1-14 answers, open questions.

## Stop rule
Two fix rounds still red: stop and report.
