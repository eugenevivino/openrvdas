"""Load, validate, and draft vessel runbooks."""

from copy import deepcopy
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path

import yaml


REQUIRED = ("stream", "endpoint", "baud", "format", "power", "spare_location",
            "escalation", "causes", "owner")
_runbooks = {}
_directory = None


def _error(setting, value, expected, example):
    return (f"{setting}: saw {value!r}; expected {expected}; "
            f"for example {example}.")


def _json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _read(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(_error(str(path), "no YAML front matter", "a leading --- block",
                                "---\\nstream: tsg1\\n---"))
    try:
        front_matter, body = text[4:].split("\n---\n", 1)
    except ValueError as error:
        raise ValueError(_error(str(path), "an unclosed YAML block", "a closing --- line",
                                "---\\nstream: tsg1\\n---")) from error
    metadata = _json_safe(yaml.safe_load(front_matter))
    if not isinstance(metadata, dict):
        raise ValueError(_error(str(path), metadata, "YAML key-value settings", "stream: tsg1"))
    for field in REQUIRED:
        if field not in metadata:
            raise ValueError(_error(field, "missing", "a runbook setting", f"{field}: value"))
    if not isinstance(metadata["causes"], list):
        raise ValueError(_error("causes", metadata["causes"], "a list", "causes: []"))
    metadata["text"] = body
    metadata["path"] = str(path)
    return metadata


def load_all(directory):
    """Load Markdown runbooks from directory and make them available to alarms."""
    global _directory, _runbooks
    _directory = Path(directory)
    loaded = {}
    for path in sorted(_directory.glob("*.md")):
        item = _read(path)
        stream = item["stream"]
        if not isinstance(stream, str) or not stream:
            raise ValueError(_error("stream", stream, "a non-empty string", "stream: tsg1"))
        if stream in loaded:
            raise ValueError(_error("stream", stream, "a unique stream", "stream: tsg2"))
        loaded[stream] = item
    _runbooks = loaded
    return deepcopy(loaded)


def _fixes(stream):
    path = _directory / "fixes.jsonl"
    if not path.exists():
        return []
    fixes = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(_error(f"fixes.jsonl line {number}", line,
                                    "one JSON object", '{"stream": "tsg1"}')) from error
        if item.get("stream") == stream:
            fixes.append(item)
    return list(reversed(fixes[-3:]))


def for_alarm(stream, stage):
    """Return a JSON-safe runbook with causes matching an alarm stage."""
    if stream not in _runbooks:
        raise KeyError(_error("stream", stream, "a loaded runbook stream", "tsg1"))
    result = deepcopy(_runbooks[stream])
    result.pop("path", None)
    result["causes"] = [
        cause for cause in result["causes"]
        if not cause.get("stages") or stage in cause["stages"]
    ]
    result["last_fixes"] = _fixes(stream)
    return result


def record_fix(stream, what, who):
    """Append one operator fix to fixes.jsonl beside the loaded runbook."""
    if stream not in _runbooks:
        raise KeyError(_error("stream", stream, "a loaded runbook stream", "tsg1"))
    for setting, value in (("what", what), ("who", who)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(_error(setting, value, "a non-empty string", f"{setting}: operator"))
    item = {"stream": stream, "what": what, "who": who,
            "timestamp": datetime.now(timezone.utc).isoformat()}
    path = _directory / "fixes.jsonl"
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(item, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())
    return item


def draft(stream, cruise_dict, history=None):
    """Create draft metadata from an OpenRVDAS cruise or port definition."""
    ports = cruise_dict.get("ports", {}) if isinstance(cruise_dict, dict) else {}
    port = ports.get(stream)
    if not isinstance(port, dict) or not isinstance(port.get("port_tab"), str):
        raise ValueError(_error(f"ports.{stream}.port_tab", None,
                                "an OpenRVDAS port_tab string",
                                "SBE21 /dev/ttyUSB0 9600 8 1 0"))
    parts = port["port_tab"].split()
    if len(parts) < 3:
        raise ValueError(_error(f"ports.{stream}.port_tab", port["port_tab"],
                                "device, endpoint, and baud", "SBE21 /dev/ttyUSB0 9600"))
    try:
        baud = int(parts[2])
    except ValueError as error:
        raise ValueError(_error(f"ports.{stream}.port_tab baud", parts[2],
                                "an integer", "9600")) from error
    result = {"stream": stream, "endpoint": parts[1], "baud": baud,
              "format": parts[0], "power": "UNKNOWN", "spare_location": "UNKNOWN",
              "escalation": "UNKNOWN", "causes": [], "owner": "DRAFT",
              "drafted": date.today().isoformat()}
    if history is not None:
        if not isinstance(history, dict):
            raise ValueError(_error("history", history, "a key-value mapping",
                                    "history: {serial: 21-1234, location: wet lab}"))
        for key in ("serial", "location"):
            if key in history:
                result[key] = history[key]
    return result


def check(directory, configured_streams):
    """Return actionable findings without hiding malformed runbook errors."""
    loaded = load_all(directory)
    findings = []
    for stream in configured_streams:
        if stream not in loaded:
            findings.append(f"{stream}: runbook is missing")
    today = date.today()
    for stream, item in loaded.items():
        if not item.get("owner") or item["owner"] == "DRAFT":
            findings.append(f"{stream}: owner is missing")
        if item.get("owner") == "DRAFT":
            try:
                drafted = date.fromisoformat(str(item.get("drafted")))
            except ValueError as error:
                raise ValueError(_error(f"{stream}.drafted", item.get("drafted"),
                                        "an ISO date", "2026-11-18")) from error
            if (today - drafted).days > 30:
                findings.append(f"{stream}: draft is stale")
        for number, cause in enumerate(item["causes"], 1):
            if not isinstance(cause, dict) or not cause.get("check"):
                findings.append(f"{stream}: cause {number} has no check")
    return findings


def to_markdown(metadata, text="Describe vessel-specific recovery details here.\n"):
    """Serialize metadata without rendering or interpreting Markdown."""
    return "---\n" + yaml.safe_dump(metadata, sort_keys=False) + "---\n" + text
