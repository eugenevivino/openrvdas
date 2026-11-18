# Onboard usability and night test (release gate for the bridge view)

From Eugene's human-factors report (2026-11-18). Targets are provisional engineering gates,
not standards. Run as an operational simulation, not a feature tour; give goals, not UI hints.

## Who and how long
6 to 8 people: at least 2 bridge officers, 2 marine techs, 2 science or shore users.
About 3 hours, on the actual bridge monitor model.

| Time | Activity |
|---|---|
| 0:00-0:10 | Consent, role, experience; system is under test |
| 0:10-0:25 | 5 min free exploration, minimal training |
| 0:25-1:35 | Six scenarios, randomized order |
| 1:35-1:50 | Break, night setup |
| 1:50-2:20 | Night tasks under bridge-night lighting |
| 2:20-2:40 | Failure recovery and AI disagreement |
| 2:40-3:00 | Debrief, severity ranking |

## Scenarios and pass targets
| Scenario | Prompt | Pass |
|---|---|---|
| Stale stream | "Is the surface temperature trustworthy right now?" | >= 90% correct; bridge detects stale within 10 s |
| QC suspect | SUSPECT injected, health OK | >= 90%; nobody calls the sensor failed from QC alone |
| Frozen sensor | Last value plausible but frozen | 100% of bridge and tech detect before acting |
| Related alerts | One root fault, several symptoms | >= 90% reach root without acking every child |
| AI disagreement | Confident, wrong AI suggestion vs raw evidence | >= 80% inspect evidence first; zero irreversible action on AI alone |
| Recovery | Network or acquisition interruption | >= 90% recover or escalate without help |
| Night | Detect warning, read value, inspect trend, ack | No critical miss; all states told apart without hue |

Metrics per task: success, time to first correct interpretation, wrong first action, help
needed, and whether the person can explain health vs quality vs freshness vs AI. Ask after
each task, same scale every time: "How certain are you?" and "How much effort did this take?"

## Night validation
Measure luminance at the normal viewing angle with night lighting set: background, primary
text, brightest normal element, red alert, yellow warning, chart grid. Record monitor
brightness, OS brightness, browser zoom, color mode, ambient setup.
After dark adaptation, each person names without a legend: PASS, SUSPECT, FAIL, NOT
EVALUATED, MISSING, AGING, STALE, sensor FAILED, an A1 alert, an AI note.
Also check for bright flashes on: refresh, login expiry, modal, loading skeleton, websocket
disconnect, route change, fullscreen exit, error page, screenshot or export, chart tooltip,
OS notification.

Run once for Night red and once for Night neutral; the bridge picks with data.
