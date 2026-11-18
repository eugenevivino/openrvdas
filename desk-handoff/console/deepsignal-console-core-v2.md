# Brief: deepsignal-console-core v2 (rulebook v2 update)

- Decision: D-CONSOLE1, within Eugene's approval of modules 1-4 (2026-11-18 05:33Z)
- Branch `deepsignal/console-core`, base head 5682671. Mac scratch `/private/tmp/deepsignal/console-core/`
- Lane: mac, `gpt-6.2-sol` high, fresh session, under 40 turns. Browser tests are run by the lead outside the sandbox (Chromium cannot run inside it).
- Read: `DESIGN.md` section "Rulebook v2 additions" (copy the new `console-DESIGN.md` over `contrib/deepsignal/console/DESIGN.md` first), then this file.

## Change exactly this
1. Freshness per DESIGN v2: expected period T per field (page file `period`, else median of last 20 intervals); LIVE <= 2T, AGING 2T-5T, STALE > 5T, NO DATA past hard timeout (default 60T, min 5 min). Remove the fixed 30 s rule. STALE keeps the value with word + age; NO DATA shows "—" plus "Last: <value> <unit> at <UTC time>". No opacity or strike-through as the only signal.
2. Data model per field: value, source timestamp, receive time, expected period, freshness, quality (from `<field>_QC` QARTOD flag if present: 1 PASS, 2 NOT EVALUATED, 3 SUSPECT, 4 FAIL, 9 MISSING; absent = NOT EVALUATED), health (UNKNOWN until console-health supplies it), ai (NONE). The number tile shows quality and freshness as separate word+shape badges; normal states (PASS, LIVE) are small and muted.
3. Two night palettes per DESIGN v2: `night_palette: red | neutral` in console.yaml (default red), plus a Red/Neutral switch next to the dimmer, stored per screen. Night red default dim changes from 60% to 80% (Impeccable flagged 2.5:1 at 60%); keep the 15% floor.
4. Persistent top-bar label "Research system monitoring".
5. Night safety: the error page, config-error panel, reconnect state and loading state all use the tokens (no light surface). Boot script sets mode before any paint, including on the error path.
6. Fix the empty first backfill (your earlier note): if the backfill window returns nothing, request the latest value once with no window so a tile is not blank until the next reading.
7. Bridge sizing per DESIGN v2: primary value 48 px, labels >= 18 px, metadata >= 16 px.

## Tests first (RED then GREEN)
- `freshness.test.ts`: T learned from intervals; boundaries at 2T, 5T, hard timeout; last-good kept.
- `quality.test.ts`: flag mapping incl. absent flag; quality and freshness independent (PASS + STALE, SUSPECT + LIVE).
- `lighting.test.ts`: both palettes; neutral keeps alarm hue distinct; red G,B <= 0.15 R at 15% and 100%.
- Extend `test_console_live.py` (lead runs it): stop publishing -> AGING then STALE; publish `<field>_QC`=3 -> SUSPECT badge while LIVE; screenshot in Night red has no pixel with G or B > 0.15 R; reload in Night never paints a light frame (sample first frame).

## Acceptance
As the core brief. Impeccable audit rerun in Day, Dusk, Night red, Night neutral; update IMPECCABLE-REPORT.md.

## Scope, banned, stop
Same as the core brief. Under 40 lines report. Two rounds still red: stop.
