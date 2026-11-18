# DeepSignal app design review

## VERIFIED

- Wrote [IA.md](IA.md), this report and ten self-contained HTML mockups. [Watch desk and page directory](index.html) opens offline.
- Files by task: index.html, instruments.html, instrument.html, add-instrument.html, first-light.html, flags.html, links.html, alerts.html, scoreboard.html and roles.html.
- The inventory contains **63 page types**. On watch 10, Instruments 9, Quality 7, Ship systems 13, Cruise desk 11, Setup and access 13. It includes ten technician journeys.
- Weather has a shipped page definition and renderer in this checkout. The supplied roadmap schedules other console modules. Feature briefs and static samples do not establish build status.
- All ten pages embed the three console fonts. Source checks passed V1 color-token use, V2 type sizes and V3 spacing, with zero exceptions. Local links, fragments, markup balance and script syntax checked.
- A scripted DOM fixture exercised lighting, search, primary review/undo flows, instrument filtering and port selection. Night red token channels stayed within the 15% limit at each integer dimmer setting from 15% through 100%.
- Browser launches ended before a screenshot. Pixel rendering, device fit and onboard luminance remain unverified. D-CONSOLE2 selects red at 80% initially and records the earlier console audit’s red contrast issue.
- The supplied SKILL.md identifies itself as 4.9.1. The brief and prior console audit identify 4.8.0. The supplied text and DESIGN.md guided this draft.

## INFERRED

- Group names, persona landings, detailed permissions and journeys are proposals based on IDEAS, ROADMAP and TARGET-PARITY. USER-JOURNEYS.md was unavailable.
- The assistant shares the watch desk, provider key settings share Roles, serial ports share Link health, and preview shares Scoreboard designer. Sample changes are local demonstrations. First-light timing is illustrative.
- Proposed approval and sign-in pages give technicians an address for a pending write or an expired session.

## Five questions for Eugene

1. Which board model, protocol manual and stale-value convention should the first scoreboard preview reproduce?
2. Who aboard may approve a science correction, an instrument configuration change and a time-limited EEZ override? Can the proposer also sign?
3. Which assistant provider and credential scope should the first vessel support: ship, cruise or individual user?
4. Which fields may leave the vessel during an EEZ hold, and how much delivery delay should Shore watch call out?
5. Which science sensor, device-server model and port should anchor the first real-sensor onboarding trial after simulated first light?
