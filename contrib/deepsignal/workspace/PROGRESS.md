# Master directive checkpoint: 2026-11-21

M1 is in progress on deepsignal/workspace-m1, based on qualified Console/Stream
Health view pilot b67f3072. Full M1 and production are not qualified. The desk
tracks 22 deliverables. DEMO-STORIES.md defines fourteen fake-cruise stories, including
future real OpenRVDAS lab acceptance rather than only mock integration.

## Verified candidate

58fbde8cb9cbab0b4a77ee25042fd9a9169d4615 includes the Relay-built Console bundle.
Relay R5 passed nine service/HTTP tests, actual 13-tool SDK stdio workflow,
model-free CLI, 281 frontend tests, lint/build/types and actual Chromium
investigation/draft/replay/export. Candidate audit is clean. Maximum queued
handoff was 0.0931 seconds, not end-to-end throughput or machine utilization.

Linux run [44879804326](https://github.com/eugenevivino/openrvdas-desk/actions/runs/44879804326)
tested that exact candidate: workspace PASS, existing-security-policy FAIL.
The unchanged policy rejected an unlisted browser_smoke.py finding. Raw scan
has 221 findings, including 33 in the new workspace: 30 smoke assertions,
subprocess import/call and URL-open checks. Disposition remains required;
no scanner policy was relaxed and this note is not independent security approval.

Raw receipts are under /private/tmp/deepsignal/product-m1-evidence/m1-r5-state/
and linux-44879804326/ under the same root. Original candidate invalidation,
browser failure and subsequent regression/repair evidence remain preserved.
Later documentation commits do not receive a new exact-head gate stamp.

| Capability | Verified scope and remaining work |
|---|---|
| Console/Stream Health | Prior fixture qualification at b67f3072; new simulated incident has browser evidence |
| Analysis/artifacts | Bounded scalar fixture and scoped artifacts; broader science/archive pending |
| Draft/replay | Actual pinned ParseTransform, two patterns, four records; general executor absent |
| MCP/CLI | Actual SDK transport and parity passed; interactive model walkthrough pending |
| Four UI routes and scalar plot | 281 frontend tests and real browser; full operator acceptance pending |
| Real manager/archive/cruise | Not implemented or qualified by this fixture |
| Grafana/InfluxDB | Mandatory G1-G6; no qualified backend connection |
| Controlled operations | No execution tool; independent approval boundary required |

Integration owner is the DeepSignal lead, claim unit-workspace-m1. Helpers have
finished. Build/test uses the frozen runtime-v11 Relay queue and guards. Kalon
owns shared allocation; no DeepSignal Mini job or production scheduling activation.

Next: disposition security findings, obtain whole-module independent science/
security/usability review and independent reference evidence; complete remaining
M1 stories and the real-upstream lab adapter. General replay/jobs, deep links,
no-change outcomes and broader operator acceptance remain incomplete. Keep HOLDs
and unfinished stamps. No service installation or production launch.

## Harness repair follow-up

Candidate6cba5716fbf1e9fd4422214dffa3995d272483c4 passed Relay readiness checks
and Linux44881969262 affected-harness-checks. Ten service/HTTP/MCP regression
checks, actual SDK/CLI, optimized-Python acceptance checks and Chromium passed.
Frontend/source reuse was checked against58fbde8c; no unchanged frontend rebuild
or expensive rerun was needed. The original full-workflow evidence remains at58fb.

The optimized-Python regression first failed for both incorrect tool catalogs;
all30 smoke assertions were replaced by mandatory checks with unchanged conditions.
The initial repair test exposed SDK exception wrapping; its original error is
preserved and the test now verifies the exact underlying failure. Browser readiness
now uses a direct loopback HTTP connection without proxies or redirects.

Unchanged Bandit policy remains FAIL:190 total findings,2 in workspace
(browser harness subprocess import/call), down from221 total/33 workspace.
No finding was suppressed or automatically accepted. Independent review and all
remaining full-scope/security/production gates remain held. Later story/docs commits
have no new exact-head gate stamp. Program architecture now requires configurable
selected access, read-only and permitted instrument modes, and protected secret
resolution; the fixture does not implement those production capabilities.
