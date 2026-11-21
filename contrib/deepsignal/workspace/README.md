# DeepSignal fixture workspace

Local, simulated investigation and configuration experiment. No AI, API key or
internet is needed after dependencies and Console assets are prepared. No live
control, manager connection, general configuration execution or Grafana API is
implemented here. Grafana is mandatory scope tracked by T-GRAF-01 through 06.

From the repository root, prepare a disposable environment (do not alter an
acquisition installation):

```sh
python3.12 -m venv /private/tmp/deepsignal/product-m1-env
/private/tmp/deepsignal/product-m1-env/bin/python -m pip install -r contrib/deepsignal/workspace/requirements-lock.txt
```

The transitive lock records the actual local environment, not a reproduced Linux
build or wheel archive. Prepare approved offline wheels before offline installation.
See `compatibility.json` for exact source hashes and unsupported profiles.

Model-free CLI demonstration:

```sh
/private/tmp/deepsignal/product-m1-env/bin/python -m contrib.deepsignal.workspace --state /private/tmp/deepsignal/workspace-demo.sqlite3 demo
```

The JSON contains a human-readable handoff and structured evidence manifest.
It freezes reference samples, calculates their summary, creates a component draft,
validates the supported fragment and replays the actual pinned ParseTransform.
The baseline rejects four records; the corrected prefix parses the four exact
expected values/timestamps. The raw fixture never changes. No deployment occurs.

After the Console build (`npm run build` in `contrib/deepsignal/console`), start
the disposable loopback UI, then open `http://127.0.0.1:8765/console/`:

```sh
/private/tmp/deepsignal/product-m1-env/bin/python -m contrib.deepsignal.workspace.http_server --state /private/tmp/deepsignal/workspace-demo.sqlite3
```

The Console's existing CDS adapter and Stream Health view receive explicitly
simulated traffic. Temperature remains stale; successful raw collection does not
turn failed parsing green. Data Explorer → Configuration Workbench → Investigations
completes the no-AI workflow. Connections reports capabilities and limits.
For the workbench choose `TEMP={temperature:g}`, validate, and run fixture replay.
The evidence uses a synthetic experiment epoch; wall-clock presentation in Console
is a display adapter and does not rewrite the stored experiment timestamps.

Tests (run through the existing Relay path under machine admission):

```sh
/private/tmp/deepsignal/product-m1-env/bin/python -m unittest discover -s contrib/deepsignal/workspace/tests -v
/private/tmp/deepsignal/product-m1-env/bin/python -m contrib.deepsignal.workspace.mcp_smoke --state /private/tmp/deepsignal/workspace-mcp-smoke.sqlite3
```

See `MCP.md` for the actual official-SDK stdio client and opt-in Codex setup.
The service applies the same permission and input checks across all three adapters.
Local process owners can alter code/state: this is not a production approval
boundary. The HTTP listener is loopback-only, uses a per-process token and strict
origin/host checks, and must not be exposed through a reverse proxy.

Scope limits: one synthetic profile, one scalar quantity, a fixed component
fragment, two reviewed parser patterns and four input records. No cruise expansion,
operator-supplied components, scientific corrections, live archives, arbitrary
queries, publication or control tools. Replay is a tiny synchronous experiment;
general asynchronous jobs/cancellation/isolation remain tracked work. Missing
samples differ from missing values. Mean is observation-weighted; deviation is
population deviation; source flags are never overwritten.

State is SQLite with bounded artifacts and investigations. Retention is local
until explicit operator deletion, with no automatic evidence eviction. Stop this
disposable server before copying its SQLite file for backup. It has no upstream
connection; stopping it cannot stop acquisition. No persistent service is installed.
See `PROGRESS.md` for tests actually run and remaining acceptance gates.
See [demo user stories](DEMO-STORIES.md) for the fake-cruise scenarios and the
distinction between this fixture and a future real OpenRVDAS lab.
