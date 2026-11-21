# Master directive checkpoint: 2026-11-21

M0 inspected; M1 implementation in progress in `deepsignal/workspace-m1`, based
on qualified pilot b67f3072. Neither full M1 nor production readiness is claimed.
The master and mandatory Grafana directives are tracked by the existing desk's
MASTER-PRODUCT-TICKETS.md, linked from TICKETS.md.

| Capability | State | Location/evidence |
|---|---|---|
| Console/Stream Health view | implemented, fixture-qualified at b67f3072 | console/src; prior exact native/Linux/independent review |
| CDS/history semantics | implemented, same qualification | console/src/cds.ts, field-data.ts |
| Upstream parser | implemented; new replay unverified | logger/transforms/parse_transform.py |
| Configuration expansion | partial; unsuitable for untrusted static validation | read_config.py, ListenerFromLoggerConfig |
| Shared analysis/artifacts | in progress | workspace/service.py |
| Draft/replay/investigation | in progress | workspace |
| MCP | new source, unverified | workspace/mcp_server.py |
| Four additional UI routes | new source, unverified | console/src/modules/workspace |
| Real archive/backend | unverified, M2 | no compatibility claim |
| Grafana/InfluxDB | mandatory, not implemented | G1-G6 tickets |
| Controlled operations | absent, M4 | no control tool registered |

Integration owner: DeepSignal lead; claim unit-workspace-m1. Helpers own disjoint
UI and MCP files and run no builds. Checks reuse Relay's frozen resource guard
and atomic execution claim. Kalon owns allocation; no Mini job is launched.
User superseded the 1% reserve on November 21: use available allowance for useful
work. No reset purchase or monetary-limit change.

Pending: service tests, SDK stdio journey, CLI parity, UI checks/browser journey,
new candidate Linux and independent review. M1 also owes connected fixture
Console/Stream Health presentation, plots/deep links, and general replay job
semantics. Preserve honest capability limits and runnable earlier work.
