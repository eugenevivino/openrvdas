# Brief: deepsignal-console-health

- Decision: D-CONSOLE1 (approved 2026-11-18 05:33Z). Risk tier: medium
- Module: console-health. Branch `deepsignal/console-health` from reviewed console-core head
- Mac scratch: `/private/tmp/deepsignal/console-health/`. Lane: mac, `gpt-6.2-sol` high; review `gpt-6.2-astra` high
- Depends on: console-core only

## Goal
A tech sees every logger worst first, with a plain line saying what to try for anything not OK.

## Build
- Health page fed by the status fields OpenRVDAS already publishes to the cache (`status:logger_status`, `status:cruise_mode`, `stderr:*`); read `server/logger_manager.py` for their exact shape and quote it in the report.
- Per logger: state (OK, Check, Stale, Down per DESIGN.md), records per second, last data age, logger name, latest stderr line shortened.
- Summary row of counts. Sort worst first, then name.
- `hints.yaml`: maps logger name or stderr pattern to a plain "what to try" sentence; sample file with 5 common cases (no data on serial port, permission denied on /dev/tty*, parse errors, disk full, clock offset).
- Read-only: no start/stop buttons.

## Failing tests first
`src/health/health.test.ts` (state mapping from status samples captured from a real LoggerManager run, sorting, hint matching), extend `test_console_live.py` with a status field publish.

## Acceptance, scope, trust, banned, report, stop
As console-core. stderr text is untrusted: render as text only. Scope: `src/health/**`, `hints.yaml`, `pages/health.yaml`, tests. Impeccable audit required. Under 30 lines.
