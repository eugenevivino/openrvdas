# Fixture MCP interface

This stdio server calls the same `Workspace.call` service as the ordinary
workspace. It contains synthetic evidence and local draft/investigation writes.
It has no acquisition approval, execution, arbitrary command, URL, or file tool.
The operator chooses the metadata database at process startup. Tool arguments
cannot select another database. The service checks deployment scope on every call.

## Compatibility and verification

Official `mcp==2.3.0` and `mcp-types==2.3.0` packages are pinned in
`requirements-mcp.txt`. Official PyPI metadata was queried on 2026-11-21.
The adapter uses the v2 `MCPServer` and `Client` interfaces. Dependencies belong
in a separate environment; do not upgrade the acquisition environment.
The integration owner records the resolved dependency manifest and check results.

**Current evidence:** implementation and smoke test written; execution pending.
Codex interactive use, cancellation under load, Linux packaging and live-vessel
qualification are not established by source inspection. Preserve original smoke
output; its JSON summary reports only what that run actually checks.

From `/private/tmp/deepsignal/product-m1-20261121`, after the isolated environment
has been prepared through the existing resource guard:

```sh
/private/tmp/deepsignal/product-m1-env/bin/python -m contrib.deepsignal.workspace.mcp_smoke --state /private/tmp/deepsignal/m1-mcp-smoke.sqlite3
```

The real SDK client starts a real stdio subprocess, lists and validates the
13-tool catalog, runs discovery → dataset → scalar analysis → configuration
correction → validation → baseline/candidate replay → investigation → export.
It compares direct-service and MCP results and checks the hand-worked statistics
(4 finite values, mean/median 15, population standard deviation √17), parser
counts (0 baseline, 4 candidate), deployment refusal, bounded input and stale
revision refusal. It makes no model call. The enclosing smoke has a 45-second
deadline; this does not qualify cancellation of arbitrary long replay jobs.

## Tools and limits

Read tools: `ds_get_system`, `ds_list_assets`, `ds_get_health`, `ds_get_artifact`.
Artifact/draft writers: `ds_query_data`, `ds_analyze`, `ds_get_configuration`,
`ds_create_draft`, `ds_validate_draft`, `ds_replay_draft`,
`ds_create_investigation`, `ds_add_finding`, `ds_export_investigation`.

Every tool requires `deployment_id`. Discover the fixed `fixture-vessel` profile
first. Query `fixture-vessel/temperature` over `[0, 6)` for the demonstration.
The returned handles are explicit and durable; transport sessions carry no
hidden selected vessel or draft. Numerical and replay results remain synthetic,
not observations of a vessel.

MCP inputs bound identifiers to 160 characters, evidence lists to 32 entries,
patterns to 128 characters, titles to 200 characters and notes to 4,000
characters. Services enforce their own limits independently. Valid responses
have a typed common envelope; expected failures become MCP tool errors with a
stable domain code and fixed safe message. Diagnostics use stderr. Client hints
about mutation are descriptive and are not authorization enforcement.

## Optional Codex registration

Installed `codex mcp add --help` and official configuration documentation were
checked on 2026-11-21. No user configuration was changed and no interactive
Codex transcript is claimed. In the trusted project, merge this entry into the
existing `.codex/config.toml` without replacing other settings:

```toml
[mcp_servers.deepsignal_fixture]
command = "/private/tmp/deepsignal/product-m1-env/bin/python"
args = ["-m", "contrib.deepsignal.workspace.mcp_server", "--state", "/private/tmp/deepsignal/m1-codex-workspace.sqlite3"]
cwd = "/private/tmp/deepsignal/product-m1-20261121"
startup_timeout_sec = 20
tool_timeout_sec = 30
```

For another checkout, substitute its actual absolute checkout, prepared Python
and owned metadata paths. Use `/mcp` to inspect the connected server, then ask for
a fixture investigation through its actual tools. The smoke test is the
reproducible model-free procedure. Returning data to a cloud-connected client
can expose it to that client; stdio does not establish a local-only AI boundary.

Sources: [official SDK](https://py.sdk.modelcontextprotocol.io/),
[stdio client](https://py.sdk.modelcontextprotocol.io/client/transports/),
[tool errors](https://py.sdk.modelcontextprotocol.io/servers/handling-errors/),
[Codex configuration](https://developers.openai.com/codex/mcp/).
