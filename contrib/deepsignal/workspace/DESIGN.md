# Fixture workspace M1

First bounded implementation of the November 21 master directive, not full
platform qualification. One integration owner: the DeepSignal lead.

Reuse Console b67f3072, its plugin contract, Stream Health/CDS, Python 3.12 and
pinned upstream ParseTransform. Do not instantiate logger configurations, scan
device definitions, change the security gateway or add another dispatcher.

Workspace supplies CLI, same-origin fixture UI and official SDK stdio MCP.
The deployment fixture-vessel is always SIMULATED. Handles are scoped content
identities, never paths. SQLite retains immutable artifacts and revisioned
investigations. Server-owned permissions apply on artifact reads too. The OS-user
boundary is not remote authentication or production approval isolation.

Raw reference samples at 0,1,4,5 have values 10,12,18,20. These are independent
expected evidence, not fabricated parser output. Simulated parsed value 9 at -1
is stale at time 6. The bad parser expects T=; records use TEMP=. The only edit
chooses one of two reviewed patterns. Replay uses only ParseTransform with fixed
synthetic records and explicit patterns, no arbitrary components or I/O.
General replay isolation and asynchronous admission remain required for larger
or operator-supplied inputs.

Authorized public test seams: Workspace.call, actual SDK stdio, ordinary CLI,
and Console interactions. Independent literals: count4, mean/median15, population
variance17, missing grid points2,3 over[0,6). Baseline parses0; corrected draft
parses4 with exact timestamps/values. A no-change draft must fail replay.

Limits: request64KiB, artifact256KiB, 512artifacts, database16MiB, queries within
the six-second fixture, at most1000rows. Retention lasts until explicit workspace
deletion; exhaustion refuses artifacts. No automatic referenced-evidence eviction.

README records runnable acceptance commands. Independent review, Linux gates,
UI acceptance and production gates remain separate. A unit test is not complete M1.
