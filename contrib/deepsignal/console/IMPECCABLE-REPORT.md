# Impeccable audit of DeepSignal Console

Impeccable 4.8.0, engine 0.1.18, ran locally with telemetry off. The checker scanned separate Day, Dusk, and Night red HTML snapshots. Each snapshot was generated from the built `dist/` bundle, its inline boot script, its stylesheet, and its shipped YAML. jsdom supplied storage and the DOM. Test doubles supplied the two cache readings and canvas context. No live or Apply command was used.

| Mode | Checker findings | Exit |
| --- | --- | --- |
| Day | 0 | 0 |
| Dusk | 0 | 0 |
| Night red, 60% | 15 occurrences of `low-contrast` | 2 |

| Technical audit | Day | Dusk | Night red | Evidence |
| --- | --- | --- | --- | --- |
| Accessibility | 3/4 | 3/4 | 2/4 | Named controls with pressed states, focus indicators, and word-and-shape status indicators. Night red falls below WCAG AA text contrast at 60%. |
| Performance | 3/4 | 3/4 | 3/4 | Local fonts, a 110.17 kB gzip JavaScript payload, no UI animation, and a cap on stored chart samples. |
| Theming | 4/4 | 4/4 | 3/4 | Each stored mode sets the page background before the app runs. Unit tests verify Night red token channels at 60% and 100%. Browser pixel coverage is pending. |
| Responsive design | 3/4 | 3/4 | 3/4 | Source defines a single-column layout under 520 px and 44 px control targets. Viewport, touch, and text zoom checks are pending. |
| Implementation integrity | 3/4 | 3/4 | 3/4 | Built snapshots show both readings, charts, and the expected pressed lighting control. A separate Day check verified that both tiles become Stale while the cache stays connected. |
| **Total** | **16/20** | **16/20** | **14/20** | Provisional scores from code and DOM evidence. |

The built display follows the rulebook's lighting, typography, and data-state design. The browser-specific checks remain open. In this sandbox, Chromium exited with `SIGTRAP` after macOS denied its Mach port bootstrap. Loopback binding was denied independently. The audit could inspect the DOM and styles, with pixel contrast, paint order on screen, chart pixels, viewport layout, and touch still unverified.

## Fixed during the audit

- The connection indicator now has a named group. Tiles explain bad readings and show the UTC time of the last stale or unavailable reading.
- Page and console configuration errors tell the operator to reload after repairing the file.
- Tailwind scans source files only, which prevents successive builds from picking up generated utility names. Two consecutive builds matched across all shipped files.

## Retained per DESIGN.md

- **P1, Night red contrast.** The checker measured about 2.5:1 for the main red and 1.5:1 for muted red at 60%. Increasing channel intensity or the default dim setting would change the prescribed Night red palette and brightness. The warning remains visible in the report.
- The statically scanned `dist/index.html` references an absolute `/console/assets/` stylesheet path as required by deployment. The standalone file scan could not resolve that path. Each mode snapshot embeds the byte-for-byte built stylesheet for the checker.
