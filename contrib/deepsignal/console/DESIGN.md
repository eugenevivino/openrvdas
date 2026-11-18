# DeepSignal Console design rulebook (DESIGN.md seed)

Source of truth for every console module. Copy into `contrib/deepsignal/console/DESIGN.md`
in console-core. Impeccable (`impeccable document`) may extend it; where Impeccable
advice conflicts with a rule here, this file wins.

Reference mockup: https://claude.ai/artifact/4vb6aXecBRQdT3k5XuXxGq (HTML copy in
project files `deepsignal-console/deepsignal-console.html`). Proposal:
https://claude.ai/artifact/XQFbM1ToqgwdbLha6Ek72z

## Lighting modes (all colors are tokens; components never use literal colors)
| Token | Day | Dusk | Night red (at dim 1.0; scale every channel by dim) |
|---|---|---|---|
| --bg | #e9eef0 | #081014 | #000000 (fixed) |
| --panel | #ffffff | #0e191f | #050000 (fixed) |
| --panel2 | #f3f6f7 | #132229 | #0a0000 (fixed) |
| --line | #c9d3d7 | #1f323b | rgb(70,8,4) |
| --fg | #0a151a | #dde8ec | rgb(255,38,16) |
| --muted | #4c5f68 | #8aa2ad | rgb(150,24,10) |
| --accent | #006a7c | #56c3d3 | rgb(255,38,16) |
| --ok / --check / --stale / --down | #1d7f50 / #a86a00 / #6b5bb5 / #b3261e | #4cc38a / #e5b440 / #a99cf0 / #ff6b5e | fg / fg / muted / rgb(255,60,30) |
| --chart / --grid | #006a7c / #d8e0e3 | #56c3d3 / #18282f | fg / rgb(40,4,2) |

Night red rules:
1. Every pixel has G and B at most 15% of R. Includes canvas charts, SVG, map, scrollbars
   (`color-scheme: dark`), inputs, focus rings, dialogs, toasts, loading states.
2. Dimmer 15-100%, default 60%, stored per screen (localStorage), applied by rewriting tokens.
3. Never a white or light frame: the first paint already uses the stored mode (inline boot
   script in index.html before CSS loads); no light default flash on load or route change.
4. One Night button in the top bar on every page, plus key N. Keys 1-9 switch pages.

## State
Four states, always word + shape + color: OK (filled circle), Check (filled triangle),
Stale (hollow square), Down (cross). Never color alone. Stale values are shown at 45%
opacity with a strike-through and "last seen <age> ago". Gaps in charts are gaps.

## Type
Numbers and labels: Barlow Semi Condensed 600. Body: Barlow. Ages and field names: IBM Plex Mono.
Fonts are bundled files (no Google Fonts at runtime). Big value 56px, medium 40px,
label 13px uppercase +0.08em tracking, tabular numerals everywhere digits appear.

## Layout
Sticky top bar: brand + ship name, page tabs, live/age pill, UTC and ship clock,
Day/Dusk, Night, dimmer (Night only). Tiles on a CSS grid, auto-fill minmax(220px,1fr),
wide = 2 columns, collapse to 1 column under 520px. Touch targets >= 44px.

## Words
Plain English, units always shown, sentence case labels, no unexplained acronyms
in UI copy (field names only in mono "source" lines).
