"""Local CLI over exactly the same service used by the console and MCP."""

import argparse
import json
from pathlib import Path
import sys
from .service import Workspace, DEPLOYMENT, LIMITS


def demo(workspace):
    def call(method, **arguments):
        result = workspace.call(method, {"deployment_id": DEPLOYMENT, **arguments})
        if result["status"] == "error":
            raise RuntimeError(result["error"]["code"])
        return result["data"]

    data = call("ds_query_data", stream_id=DEPLOYMENT + "/temperature", start=0, end=6)
    analysis = call("ds_analyze", dataset_id=data["dataset_id"])
    config = call("ds_get_configuration")
    draft = call(
        "ds_create_draft", base_snapshot_id=config["snapshot_id"], pattern="TEMP={temperature:g}"
    )
    validation = call("ds_validate_draft", draft_id=draft["draft_id"], revision=1)
    replay = call(
        "ds_replay_draft", draft_id=draft["draft_id"], revision=1, dataset_id=data["dataset_id"]
    )
    investigation = call(
        "ds_create_investigation",
        title="Simulated temperature parser incident",
        evidence_ids=[
            data["dataset_id"],
            analysis["artifact_id"],
            config["snapshot_id"],
            draft["draft_id"],
            validation["artifact_id"],
            replay["artifact_id"],
        ],
    )
    call(
        "ds_add_finding",
        investigation_id=investigation["investigation_id"],
        expected_revision=1,
        kind="hypothesis",
        text="Prefix mismatch explains this fixture replay; live causes remain unknown.",
        evidence_ids=[replay["artifact_id"]],
    )
    return call("ds_export_investigation", investigation_id=investigation["investigation_id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("method", help="demo, or an implemented ds_* method")
    parser.add_argument(
        "--arguments", default="{}", help="bounded JSON object; no paths or endpoints"
    )
    args = parser.parse_args()
    workspace = Workspace(args.state)
    if args.method == "demo":
        result = demo(workspace)
    else:
        if len(args.arguments.encode()) > LIMITS["request_bytes"]:
            parser.error("arguments exceed limit")
        try:
            arguments = json.loads(args.arguments)
        except (ValueError, RecursionError):
            parser.error("arguments must be JSON")
        result = workspace.call(args.method, arguments)
    print(json.dumps(result, indent=2, allow_nan=False))
    if result.get("status") == "error":
        sys.exit(2)


if __name__ == "__main__":
    main()
