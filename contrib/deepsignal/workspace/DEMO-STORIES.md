# Simulated cruise: MCP and operator acceptance stories

Requested by Eugene on 2026-11-21. This is an acceptance backlog, not a claim
that the real OpenRVDAS demo already exists. Reuse Relay and the shared UI/CLI/MCP
services. Tickets are in the desk's MASTER-PRODUCT-TICKETS.md.

## Demo stages

1. **Current fixture:** fixture-vessel, actual MCP SDK and upstream ParseTransform,
   simulated CDS presentation. No running upstream manager or real archive adapter.
2. **Real upstream lab:** pinned disposable OpenRVDAS, fake cruise DS-DEMO-001,
   vessel DeepSignal Demo, simulated sensors, stock acquisition and a real local
   archive. Discover the actual management backend/capabilities. Not implemented yet.
3. **Extended lab:** supported Grafana/InfluxDB and independently approved lab
   management operations, each with separate implementation and acceptance gates.

Every screen, tool result and export identifies simulation, deployment, source
version and time basis; cruise identity appears where supported. Use owned scratch
files, isolated state and loopback ports, with existing resource admission. No
vessel endpoints or hardware. Acquisition must survive stopping DeepSignal/MCP.
Use upstream sample-cruise structures only after checking supported schema and
redistribution terms; do not invent configuration keys.

## Scenario to implement

Use an explicit UTC epoch, fixed seed and repeatable event schedule. Include
synthetic navigation, meteorology and seawater streams with declared units and
cadences, several healthy streams, a mode-dependent logger intentionally off,
a plausible stale value, missing records and one parser fault. Fabricated readings
do not establish instrument accuracy or physical correctness.

Preserve raw inputs and an independently checked truth manifest declaring exact
values, timestamps, parser outputs, gaps, mode transitions and injected faults.
Expected results must not come from the analysis/parser code under test. Record
generator/configuration/upstream/dependency versions and input/output hashes.
Keep the six-second temperature regression unchanged under its existing identity;
give the longer cruise its own identity and evidence.

## User stories and expected results

| ID / user goal | Example MCP prompt | Required outcome and evidence | Tickets / current state |
|---|---|---|---|
| DEMO-01: Technician understands the installation at watch start | Describe this demo cruise, sensors, units and available capabilities. What is unknown? | Actual catalog/profile, simulation and source identity; UI/MCP agree; absent metadata remains unknown. Save discovery snapshot and walkthrough. | T-PROD-00,02,03,10; fixture partial, real lab pending |
| DEMO-02: Technician distinguishes inactive from failed | Which streams need attention? Explain using mode, cadence, freshness and acquisition evidence. | Healthy stays healthy; intentionally inactive is not failed; plausible old value stays stale; unknown expectations remain unknown. Save truth timeline and health/event/UI results. | T-PROD-01,05,06,10; stale fixture partial |
| DEMO-03: Technician investigates a parser fault | Investigate this stale temperature over the selected interval. Separate observations from hypotheses and cite evidence. | Freeze bounded dataset; separate raw arrival, parsing and delivery; retain QC/units/time; no unsupported physical-fault claim. UI/CLI/MCP agree on dataset/analysis identity. | T-PROD-01,03,04,09,10; bounded fixture passed at 58fbde8c |
| DEMO-04: Technician tests a minimal repair | Draft the smallest supported correction, show the diff, validate and replay both versions on identical raw input. Do not apply. | Immutable base-bound draft; validation levels explicit; temperature regression gives 0 baseline and 4 candidate records with values 10,12,18,20 at 0,1,4,5. Unchanged draft fails repair acceptance. No deployment. Save both outputs and independent literals. | T-PROD-07,08,10; fixed-component fixture passed, general lab pending |
| DEMO-05: Scientist avoids an unjustified change | Is a configuration change justified by this gap? What cannot be concluded? | Expected inactivity or insufficient archive evidence yields no-change/inconclusive with reasons. Missing is not zero; unknown cadence gives no guessed loss percentage; no invented interpolation/correction. Save a distinct no-change fixture and decision. | T-PROD-01,03,04,05,09; full acceptance pending |
| DEMO-06: Outgoing technician hands over the watch | Export the interval, evidence, draft, tests, uncertainties and next safe action for the next watch. | Readable and structured export; another person resumes without chat/model; failed evidence preserved, stale revisions conflict. Save export plus second-person resume checklist. | T-PROD-09,10,14; fixture export passed, human resume pending |
| DEMO-07: Operator recovers from an outage | What happened during the interruption, and what coverage is verified? | Bounded retries; retained data remains stale; reconnect gaps explicit. Stop only owned DeepSignal/MCP: upstream acquisition/native administration continue. Restart preserves artifacts without duplicate operations. Save fault timeline and acquisition counts. | T-PROD-02,03,10,13; real lab pending |
| DEMO-08: Scientist prepares an underway dashboard | Draft an underway-science dashboard from available navigation, weather and seawater fields; flag missing fields and preview without publishing. | Verified mappings, units, supported panels, bounded queries and gap/QC/circular semantics. Shared UI/MCP draft. Publication requires independent approval; saved definition, queries and visual acceptance checked separately. | T-GRAF-01 through 06, T-PROD-10; extended lab pending |
| DEMO-09: Owner enforces scope and permissions | Apply this draft now, while using an unapproved identity. | Refusal/unavailable execution, no mutation. Wrong deployment, stale handles and oversized requests fail explicitly. Trusted identity cannot be replaced by a prompt assertion. Save transport refusal checks and independent review. | T-PROD-10,11,12; fixture refusals partial, production boundary pending |
| DEMO-10: Authorized lab operator applies a reviewed repair once | Show the independently approved lab operation and verify its outcome. | Approval binds deployment/base/draft/action/expiry. Proven manager adapter records intent, executes once and verifies loaded state/fresh data. Reject stale proposal; reconcile ambiguous responses before retry. Save actual backend and audit evidence. A mock executor is insufficient. | T-PROD-11,12,13; M4 pending, executor unavailable |

## Run record and completion

For each story record exact candidate, profile/config/input hashes, runner/client
versions, permissions, prerequisites, commands/operator steps, timestamps, observed
results, raw evidence paths, verdict and next action. Unsupported, unrun and HOLD
are distinct from PASS. Preserve failed attempts and original observations.

Run deterministic service/CLI checks, actual SDK transport and ordinary browser
journeys through Relay. Add a real interactive MCP-client walkthrough separately
when an authorized client is available; SDK tests do not prove model behavior.
Reuse valid unchanged evidence. Measure task completion and acquisition interference;
test counts alone do not prove usability. Independent science/security/usability
review remains required. No live-vessel activation follows a demo pass.
