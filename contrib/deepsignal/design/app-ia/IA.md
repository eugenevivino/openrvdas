# DeepSignal app inventory

Design draft for the 18 November 2026 console-contract checkout. [Open the sample watch desk](index.html).

| Reading the inventory | Convention |
|---|---|
| Unit of count | 63 page types. A per-logger route counts once. A panel, preview or tab with its own address can be a destination. A single static mockup can show several destinations. |
| Status evidence | **MVP built** means a page configuration and renderer exist in this checkout. **Briefed** means the supplied contract, roadmap, parity plan or feature brief describes its surface or backing work. **New** means the page is a design proposal. A briefed module can still need a new page. |
| Source evidence | FieldState, logger status fields, page registration and alerts follow CONTRACT.md. Named future modules and stores describe proposed inputs. The console reads through ctx.store, with one cache connection. |
| Scope | IDEAS numbers trace product jobs. Engineering-only ideas such as the build gate have no crew page. Research signals share a product-detail template. Routes, owners and navigation are inferred. |
| People | “All” means bridge, tech, science, shore and admin. Persona selects a starting view. Authenticated role and vessel scope decide permissions. |
| Inventory sources | Local DESIGN.md, CONTRACT.md, mockup.html, IDEAS.md, ROADMAP.md, TARGET-PARITY.md, DECISIONS.md, console example.yaml and ServerAPI. USER-JOURNEYS.md was unavailable. |

## Sitemap

```text
DeepSignal · current vessel / cruise
├─ On watch (10)
│  ├─ W01 Watch desk
│  ├─ W02 Bridge
│  ├─ W03 Science
│  ├─ W04 Health
│  ├─ W05 Self-test
│  ├─ W06 Automatic instrument page
│  ├─ W07 Weather
│  ├─ W08 Map
│  ├─ W09 Alerts history
│  └─ W10 Shore watch
├─ Instruments (9)
│  ├─ I01 Instruments and loggers
│  ├─ I02 Instrument detail
│  ├─ I03 Add instrument
│  ├─ I04 Swap instrument
│  ├─ I05 Calibrate
│  ├─ I06 Instrument history
│  ├─ I07 Logger detail
│  ├─ I08 Instrument profiles
│  └─ I09 Config review
├─ Quality (7)
│  ├─ Q01 Flags review
│  ├─ Q02 Quality tests
│  ├─ Q03 Drift report
│  ├─ Q04 Correction review
│  ├─ Q05 Correction ledger
│  ├─ Q06 Replay and reanalysis
│  └─ Q07 Derived products
├─ Ship systems (13)
│  ├─ S01 Link health
│  ├─ S02 Serial device servers
│  ├─ S03 Sonar watch
│  ├─ S04 Motion and position
│  ├─ S05 Transmit timeline
│  ├─ S06 Current profiler
│  ├─ S07 Casts and winch
│  ├─ S08 Engineering feeds
│  ├─ S09 Connections register
│  ├─ S10 Seismic shot quality
│  ├─ S11 Streamer quality
│  ├─ S12 Protected-species watch
│  └─ S13 Host health
├─ Cruise desk (11)
│  ├─ C01 Cruise record
│  ├─ C02 Event log
│  ├─ C03 Route and stations
│  ├─ C04 EEZ and clearance
│  ├─ C05 Scoreboard designer
│  ├─ C06 Scoreboard preview
│  ├─ C07 Exports and archive
│  ├─ C08 Cruise assistant
│  ├─ C09 OpenVDM delivery
│  ├─ C10 Sealog events
│  └─ C11 Grafana dashboards
└─ Setup and access (13)
   ├─ A01 First light
   ├─ A02 Cruise configuration
   ├─ A03 Users
   ├─ A04 Roles
   ├─ A05 Service API keys
   ├─ A06 Assistant provider key
   ├─ A07 Audit log
   ├─ A08 MCP connections
   ├─ A09 Station settings
   ├─ A10 Release and shore policy
   ├─ A11 Alert rules
   ├─ A12 Sign in and recover access
   └─ A13 Change approvals
```

## Page inventory

### On watch

| ID | Page | Who | One job | Main content | Data source | IDEAS | Status |
|---|---|---|---|---|---|---|---|
| W01 | Watch desk | all | Pick up the watch | Active faults, last shift events, destinations | Cruise context + alert groups + event log | 9,14,15 | new |
| W02 | Bridge | bridge | Spot a change at a glance | One screen of wind, heading, speed, depth and highest exception | PortTrueWindSpeed, S330HeadingTrue, S330SpeedKt, Knud3Depth | 4,13,50 | briefed |
| W03 | Science | science | Assess underway measurements | Parameter groups, unit-labelled trends, gaps, QC filter and provenance | TsgTemp, TsgSal, FlrChl, matching QC fields | 8,14,57 | briefed |
| W04 | Health | tech | Locate a failing logger | Matrix of health, quality, freshness and last stderr per logger | status:logger_status, stderr:logger:&lt;logger>, ctx.store | 12,61,119 | briefed |
| W05 | Self-test | tech | Find a broken console dependency | Cache handshake, page validation, decoder and clock checks, recovery hint | Console self-test module + PageProblem | 12,124 | briefed |
| W06 | Automatic instrument page | bridge, tech, science | Read a newly discovered stream | One route per logger, fields, units, age, and local override | describe(field), ctx.pages.register(), page YAML | 12,14,125 | briefed |
| W07 | Weather | bridge, science | Read the example weather station | Air temperature and relative humidity with history | example.yaml, MwxAirTemp, MwxAirRelHumid | 13,14 | MVP built |
| W08 | Map | bridge, science | Place a reading along the track | Offline basemap, clickable track, layers and event times | S330Latitude, S330Longitude, Map module + event log | 107 | briefed |
| W09 | Alerts history | bridge, tech, shore | Trace a fault from onset to recovery | Grouped tiers, first action, ack, shelving expiry, reopen and linked events | ctx.alerts + proposed history store | 9,12,34 | new |
| W10 | Shore watch | shore | Tell ship failure from delayed delivery | Fleet → cruise, last snapshot, source time, receive time and backlog | Snapshot receiver + link profile + FieldState times | 14,17,18,19,35,44,123 | new |

### Instruments

| ID | Page | Who | One job | Main content | Data source | IDEAS | Status |
|---|---|---|---|---|---|---|---|
| I01 | Instruments and loggers | tech, science | Find the right stream | Search by serial, logger, location or role, separate state columns | Registry #52 + ServerAPI.get_loggers() + ctx.store | 12,52,61 | briefed |
| I02 | Instrument detail | tech, science | Identify what is installed | Serial, location, logger, readings, cal history, documents and profile link | Registry, get_logger(), describe(field), calibration records | 7,52,61,118 | briefed |
| I03 | Add instrument | tech | Bring a real sensor into logging | Detect local input, identify device, map units and QC, attach cal, preview diff, verify first value | Setup engine #114/#125-128 + ServerAPI config readback | 29,114,121,125,126,127,128 | briefed |
| I04 | Swap instrument | tech | Replace hardware without losing lineage | Old/new serials, same role, effective time, coefficient and mapping diff | Registry installs #52 + versioned config #126 | 7,52,106 | new |
| I05 | Calibrate | tech, science | Register an effective calibration | Certificate, reference, units, coefficients, residuals and before/after example | Calibration transform #7 + registry + documents | 7,22,52,118 | new |
| I06 | Instrument history | tech, science, shore | Reconstruct a deployment | Append-only swaps, cals, maintenance, config hashes, serial and cruise filters | Instrument history graph + #130 byte-log references | 7,32,52,130,152 | briefed |
| I07 | Logger detail | tech | Diagnose acquisition | Active mode/config, last input, parsed rate, stderr tail and linked port | ServerAPI.get_logger_config(), status:cruise_mode, stderr:logger:&lt;logger> | 12,61,156 | new |
| I08 | Instrument profiles | tech, admin | Maintain reviewed device recipes | Model, units, init steps, allowed replies, timeouts, revision and preview | Device pack, #130 init profiles, component catalog | 45,121,128,130 | briefed |
| I09 | Config review | tech | Resolve a configuration mismatch | Readback vs inventory, linter findings, proposed diff, backup, approval and verify/rollback | #126/#127, snapshot reader, advisor, #65 apply service | 126,127,129,152,153,154 | briefed |

### Quality

| ID | Page | Who | One job | Main content | Data source | IDEAS | Status |
|---|---|---|---|---|---|---|---|
| Q01 | Flags review | tech, science | Explain a flagged observation | Field, UTC window, raw trend, aggregate flag, test result and reason | &lt;field>_QC, &lt;field>_QC_&lt;test>, &lt;field>_QC_reason | 8,55 | briefed |
| Q02 | Quality tests | tech, science | Set limits for one field | Range, spike, rate and flat-line settings, units, replay preview and version diff | QARTOD transform config + replay cache | 8,110 | new |
| Q03 | Drift report | science, tech, shore | Decide if drift is identifiable | Paired and independent references, trends, cal events, front hypothesis, cannot-tell verdict | Drift engine + CTD/bottle matches + registry lineage | 10,11,36,54,55,74,76 | briefed |
| Q04 | Correction review | science, tech | Decide on a proposed correction | Affected interval, evidence, uncertainty, raw vs corrected trace, approver and expiry | Correction ledger + evidence graph + #65 approval | 54,55,56,65 | briefed |
| Q05 | Correction ledger | tech, science, shore | Trace or reverse a signed correction | Version chain, signer, downstream products, rollback preview and compensating revision | Append-only #56 ledger + signed manifests | 32,56,66 | briefed |
| Q06 | Replay and reanalysis | science, shore | Compare transforms on the same cruise | Raw interval, old/new outputs, withheld tests, product version and lineage | Replay reader + legacy archive + provenance manifest | 32,33,59,60,63 | new |
| Q07 | Derived products | science, tech | Inspect a computed ocean or vessel signal | Method, inputs, regime, uncertainty, available sea-state, machinery and acoustic products | Product catalog + registered transform fields + evidence graph | 25,38,39,40,41,42,51,57,78,79,80-103,106,112,129 | new |

### Ship systems

| ID | Page | Who | One job | Main content | Data source | IDEAS | Status |
|---|---|---|---|---|---|---|---|
| S01 | Link health | tech, shore | Isolate a stream interruption | Per-link verdict, cadence, management reachability, stderr, NOC incident and timestamps | #156 adapter + status:logger_status + receiveTime | 12,156 | briefed |
| S02 | Serial device servers | tech | Trace a port to its logger | Model/driver, port settings, client, RX/errors, expected mapping and proposed mismatch fix | #157 read-only management adapter + config + #156 | 153,156,157 | briefed |
| S03 | Sonar watch | tech, science | Spot degraded survey coverage | Ping rate, beam fraction, clock, file growth, applied sound speed and depth consensus | #139 summaries, #140 comparisons, #141 consensus, #143 heartbeat | 139,140,141,143 | briefed |
| S04 | Motion and position | tech, bridge | Find divergent timing or position | Recorded vs input attitude lag, offset, RMS, bridge feed source and time | #138 IEC feed, POS MV data port, Seapath quality, #142 alignment | 31,38,113,138,142,146 | new |
| S05 | Transmit timeline | tech, science | Find overlapping acoustic transmissions | Aligned multibeam, profiler and current-meter ping windows and gaps | #144 passive synchronizer summaries | 94,144 | new |
| S06 | Current profiler | tech, science | Check ADCP delivery and alignment | Ensemble cadence, bottom-track percent good, heading differences and test words | UHDAS/VmDAS or PD0 summaries | 41,145 | new |
| S07 | Casts and winch | tech, science | Follow a cast and assess profile currency | Wire out, tension, package depth, last sound-speed profile time and distance | Winch-data-processing outputs + #147 read-only cast files | 109,136,147 | new |
| S08 | Engineering feeds | tech | Check machinery telemetry | Engine load, power and tank trends with register scaling and gateway source | Read-only Modbus map and receive-only NMEA 2000 gateway | 43,98,99,148,149 | new |
| S09 | Connections register | tech, admin | Verify the receive-only boundary | Gateway or mirror, permitted direction, owner, placement checklist and lint result | #151 connection register + #127 lint + scoped access inventory | 138,149,151,155 | new |
| S10 | Seismic shot quality | science, tech | Review shot spacing and timing | Missed shots, interval, fire time vs GPS and interpolated fix | #158 listen-only controller log + ship nav, P1/11 subset | 158 | briefed |
| S11 | Streamer quality | science, tech | Locate a degraded channel | Bird depth/heading, feather, noisy/dead channels and coverage gaps | #159 controller output or SEG-D/SEG-Y headers and traces | 159 | new |
| S12 | Protected-species watch | science, bridge | Monitor mitigation context | Observer view of source state, ramp-up, shutdown events, edge distance, timeline and Sealog link | #158 listen-only feed + #137/#144 + #133 events | 133,137,144,160 | new |
| S13 | Host health | tech, shore | Find resource exhaustion | Disk growth by volume, time to full, CPU, RAM, clock offset and service restarts | #119 host metrics + archive manifest | 12,119,135 | briefed |

### Cruise desk

| ID | Page | Who | One job | Main content | Data source | IDEAS | Status |
|---|---|---|---|---|---|---|---|
| C01 | Cruise record | tech, science, shore | Set the working cruise context | Dates, ports, participants, lowering, source precedence and vessel geometry | #120 cruise metadata extended by #132, registry offsets | 113,117,120,132 | briefed |
| C02 | Event log | bridge, tech, science, shore | Reconstruct a watch | Stations, casts, watch notes, suggestions, linked samples, author and amendments | #15 events + Sealog aux data + ServerAPI.get_message_log() | 15,28,33,133 | briefed |
| C03 | Route and stations | bridge, science | Estimate time to the next station | Imported waypoints, along-track distance, ETA at stated speed and source age | #108 route module, RTZ or RTE/WPL import + S330SpeedKt | 107,108,150 | briefed |
| C04 | EEZ and clearance | bridge, tech, science | Determine required acquisition policy | Clearance record by zone/instrument, edge ETA, log/quarantine/stop, fix loss and dated overrides | Offline Marine Regions polygons + cruise clearance + position + #137 audit | 116,137 | briefed |
| C05 | Scoreboard designer | tech | Lay out a display page | Board model, cell order, source, units, stale format and version diff | ScoreboardWriter layout + describe(field) | 5,50 | new |
| C06 | Scoreboard preview | bridge, tech | Proof a board before release | Model-sized page, cell width, cadence, sample/live age and missing-field rendering | #5 formatter + latest cache values | 5,50 | new |
| C07 | Exports and archive | science, tech, shore | Deliver a reproducible data package | QC bins, ERDDAP subset, SAMOS/FM-13, manifest, compression, verify and transfer queue | #104 datasets, #111 writers, #135 archive, #17 sync | 6,16,17,58,104,105,111,135 | briefed |
| C08 | Cruise assistant | tech, science, shore | Ask a bounded question of cruise data | Key status, query window, evidence links, model/version, suggestions and logged dispositions | MCP read tools + evidence/proposal store + provider key status | 20,21,22,23,27,30,37,62,64,66,67 | new |
| C09 | OpenVDM delivery | tech, shore | Check cruise-package delivery | Collection name, last friendly file, qualityTests, stats and rejected items | #131 bridge dashboard + OpenVDM warehouse cruise context | 131,132,135,136 | briefed |
| C10 | Sealog events | tech, science | Check event handoff | Latest event, aux QC, outbound queue, last receipt and fault | #133 SealogWriter + aux inserter | 15,133,136 | briefed |
| C11 | Grafana dashboards | tech, science | Check dashboard provisioning | Cruise dashboard links, field tags, last Influx write and rule coverage | #134 Grafana pack + InfluxDB quality fields | 8,134 | briefed |

### Setup and access

| ID | Page | Who | One job | Main content | Data source | IDEAS | Status |
|---|---|---|---|---|---|---|---|
| A01 | First light | tech, admin | Verify the install has reached live simulated data | Action count, elapsed clock, cache handshake, changing sample and next real sensor | #124 install clock + simulator + console store | 71,124 | briefed |
| A02 | Cruise configuration | tech, admin | Review and deploy acquisition settings | Saved cruise profiles, generated modes, source selection, diff, lint and restore point | ServerAPI.get_configuration()/get_modes(), #126/#127 + #65 | 106,125,126,127,128 | briefed |
| A03 | Users | admin | Manage a person's access | Account, vessel scope, assigned role, sessions and expiry | #115 account directory | 115 | briefed |
| A04 | Roles | admin | Review and change a crew member's permissions | Public/science/tech/admin matrix, vessel scope, effective permissions, diff and history | #115 grants + #62 audit | 62,115 | briefed |
| A05 | Service API keys | admin | Manage machine access | Client, scope, last use, expiry, rotate/revoke and replacement reference | MCP remote token service + audit | 62,64,68,115,156 | new |
| A06 | Assistant provider key | admin | Connect an approved AI provider | Provider, key presence, masked reference, test result and version switch | Proposed server-side secrets store + MCP gateway settings | 23,62,64 | new |
| A07 | Audit log | admin, tech | Trace who changed what | Actor, scoped object, diff, reason, timestamp, evidence, reversal and integrity | #62 audit + #56 ledger + #65 approvals + scoped access log | 32,56,62,65,155 | briefed |
| A08 | MCP connections | admin, tech | Inspect client access to ship data | Local or remote client, role, transport, query budgets, last request and doctor result | MCP setup-client/doctor + scoped tokens + audit | 20,23,64,65,66,67,68 | briefed |
| A09 | Station settings | bridge, tech, admin | Fit the console to this screen | Startup watch, installed page order, ship time, lighting preference and density | console.yaml, public/pages, per-screen display storage | 13,14 | new |
| A10 | Release and shore policy | admin, shore | Set what leaves the ship | Held fields, retention, zone restrictions, priority, snapshot cadence and link profile | #116 release rules + eez_inside + #19 sync profiles | 17,18,19,35,116,123,137 | briefed |
| A11 | Alert rules | tech, admin | Tune a watch rule | State/persistence, tier, consequence, first action, test window and prior revision | #9 rules + deterministic #34 compiler + alert log | 9,34,55 | new |
| A12 | Sign in and recover access | all | Open a scoped crew session | Ship/shore identity, expired session, local recovery contact, return to original page after sign-in | #115 identity service + station policy | 115 | new |
| A13 | Change approvals | tech, admin | Resolve a pending apply request | Target, proposer, single diff, scope, expiry, verification and rollback receipt | #65 approval service + #154 change record + #62 audit | 62,64,65,154 | new |

## Starting a watch and moving between groups

| Persona | Start | First drill-down |
|---|---|---|
| Bridge | W02 Bridge, glance density | Select a flagged value for W06 or a banner for W09. Restore Bridge with one tap. |
| Tech | W04 Health, summary density | Failed logger → I07 → S01/S02, retaining the logger and time window. |
| Science | W03 Science | Select a field interval → Q01 → I06 or Q03, retaining the observation time and serial. |
| Shore | W10 Shore watch | Choose vessel/cruise → delayed snapshot → C02 or S01, carrying source and receive times. |
| Admin | A03 Users | Choose person and vessel → A04 → A07. A clean station opens A01 first. |

| Shared chrome or link | Behavior |
|---|---|
| Watch bar | Ship, cruise, “Research system monitoring”, cache connection with age, UTC and ship clock. A live connection describes transport only. Persistent group links plus group-local page list. Brand returns to W01. |
| Alert slot | Show highest abnormal root cause across groups, tier, source, consequence, age and first action. W09 opens its children and history. A1/A2 require a named acknowledgement. Shelving shows who, why and expiry. |
| Find a page | Palette searches allowed destinations by task, field or logger. Enter opens in current context, Escape returns focus. Keys 1 to 6 open groups, N toggles Night outside text entry. |
| Lighting | Day, Dusk, Night red and Night neutral. One Night button uses station preference, red at 80% initially per D-CONSOLE2. Dim 15% to 100%, restore before paint. |
| Context | Links carry vessel, cruise, logger/serial, field and UTC interval where applicable. Breadcrumb/back restores filters, scroll and selection. Shore identifies receipt delay separately from source age. |
| Depth | Glance → summary → diagnostics by selecting a reading, then its source. Health, freshness, QC and AI each have their own state. Missing QC means not evaluated. |
| First light | Clean Ubuntu 24.04 → run defaults command → enter sudo password if prompted → open console URL with live simulated data. Count each action and all elapsed time. Target ≤10 min and ≤3 actions, one server. T1 real sensor is a separate ≤15 min / ≤10 actions / zero-YAML target. |

## Where changes happen

| Surface | Boundary and return path |
|---|---|
| Monitoring | Bridge, Science, shore, sensor values, link/port diagnostics, protected-species and ship systems are read-only. Ship controls remain in vendor software per D-SHIP1. Probes are opt-in on management interfaces. |
| Local display | Lighting, filters and draft previews apply immediately to this screen. The previous selection restores them. |
| Cruise changes | Open the relevant editor. A single review shows target/serial, scope, old → new, effective time, effect and restore point. One named confirmation commits. Show verification and Undo at the receipt and in history. Retried submissions use the same proposal. |
| Apply service | MCP and AI can read or propose. A named authorized person on ship reviews one expiring change at A13, also reachable from its editor. Only the apply service writes. Allowlisted science/DAS changes take a backup, verify on live data and roll back on failure. |
| History and exceptions | Undo appends a compensating entry. Reopen an acknowledged alert, end a shelf/EEZ override, restore the previous calibration/config, or supersede a correction. Rotate a revoked secret by issuing a replacement. Lost samples and physical actions cannot be reversed. |
| EEZ and clearance | Compare the per-instrument clearance with the current zone. Lost position uses the strictest action within 24 nm of last fix, or the uncleared action for every logger without a last fix (D-137A). An override records approver, reason, scope, expiry and return to policy. |
| Credentials | A05 service tokens authorize clients. A06 provider credentials are managed server-side. Show secret presence and audit reference only. Viewing W01 and using local quality tools require neither a provider nor a provider key. |

## Ten technician journeys

Inferred from IDEAS.md, ROADMAP.md and TARGET-PARITY.md. GAP denotes a step outside the proposed page inventory. Actions and timings need an observed run.

| Job | Page path in order | Done when |
|---|---|---|
| 1. First light | GAP run installer and authenticate at host → A01 First light → W07 Weather | Simulated readings update, age is live, clock and action count recorded at first value. Opening Weather afterward is optional. |
| 2. Add a real sensor | GAP attach sensor → I01 → I03 detect/map/preview → I09 config diff → A13 approve/apply → I07 → W06 | Expected field parses, logs and appears with units, quality and freshness. |
| 3. Recover a dead sensor | W04 → W09 → I07 stderr → S01 → S02 → GAP inspect cable/power → I02 → W09 | New source timestamps advance and root cause closes with recovery time. |
| 4. Swap a failed unit | I02 → I04 → GAP fit replacement → I09 verify → I06 | New serial supplies the old role, with both deployment intervals retained. |
| 5. Calibrate against a reference | I02 → GAP take reference measurement → I05 → I06 → Q01 | Version, effective time, certificate and independent check are linked. |
| 6. Diagnose a link drop | W09 → S01 → S02 port/client → I07 → I09 if approved settings differ → S01 | Logger and port counters both advance. Management reachability alone is insufficient. |
| 7. Respond to a filling disk | W09 → S13 → C07 verify closed-file archive → GAP expand storage on host → S13 → W09 | Volume has headroom, manifest verifies and logging continues. Originals retained by default. |
| 8. Review a suspect temperature | W03 → Q01 → I06 → Q03 → Q04 → Q05 | Independent evidence supports the signed version or a cannot-tell verdict. Use Q05 to reverse a correction. |
| 9. Approach a clearance boundary | W08 → C04 → I07 → C02 → A07 | Applied logger dispositions match clearance. Any override has an owner, reason and expiry. |
| 10. Change a scoreboard cell | C05 → C06 → C05 review layout diff → C06 → GAP observe physical board | Approved formatter shows the intended field, units and stale state on the installed board. |
