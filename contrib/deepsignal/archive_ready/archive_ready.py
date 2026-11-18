"""Build and check an append-only archive-readiness manifest."""

from datetime import datetime, timezone
import glob
import hashlib
import json
from pathlib import Path
import re

import yaml


def _error(setting, value, expected, example):
    raise ValueError(
        f"Setting '{setting}' was {value!r}; expected {expected}; for example {example}."
    )


def _parse_time(value, setting):
    if not isinstance(value, str):
        _error(setting, value, "an ISO 8601 timestamp", "2024-01-31T12:00:00Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        _error(setting, value, "an ISO 8601 timestamp", "2024-01-31T12:00:00Z")


def load_expected(path):
    """Safely load and validate an expected-dataset YAML file."""
    with Path(path).open(encoding="utf-8") as stream:
        expected = yaml.safe_load(stream)
    _validate_expected(expected)
    return expected


def _validate_expected(expected):
    if not isinstance(expected, dict) or not isinstance(expected.get("datasets"), list):
        _error("datasets", expected, "a list of dataset mappings", "datasets: []")
    for number, dataset in enumerate(expected["datasets"]):
        prefix = f"datasets[{number}]"
        if not isinstance(dataset, dict):
            _error(prefix, dataset, "a mapping", "name: met")
        for key in ("name", "glob"):
            if not isinstance(dataset.get(key), str) or not dataset[key]:
                _error(f"{prefix}.{key}", dataset.get(key), "a non-empty string", f"{key}: met")
        cadence = dataset.get("cadence_seconds")
        if not isinstance(cadence, (int, float)) or cadence <= 0:
            _error(f"{prefix}.cadence_seconds", cadence, "a positive number", "cadence_seconds: 60")
        if not isinstance(dataset.get("required"), bool):
            _error(f"{prefix}.required", dataset.get("required"), "true or false", "required: true")


def _walk(value):
    if isinstance(value, dict):
        if value.get("class") == "LogfileWriter":
            yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def generate_expected(cruise_dict):
    """Propose expected datasets from every LogfileWriter filebase."""
    datasets = {}
    for writer in _walk(cruise_dict):
        filebase = writer.get("kwargs", {}).get("filebase")
        filebases = filebase.values() if isinstance(filebase, dict) else [filebase]
        for base in filebases:
            if not isinstance(base, str) or not base:
                continue
            name = Path(base).name.rsplit("_", 1)[-1]
            datasets[base] = {
                "name": name,
                "glob": f"{base}-*",
                "cadence_seconds": 1,
                "time_field": 0,
                "filename_date_pattern": r"(\d{4}-\d{2}-\d{2})(?:T\d{2})?$",
                "required": True,
                "parser": "delimited",
            }
    return {"datasets": list(datasets.values())}


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_cache(path):
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _timestamps(path, field):
    values = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                if isinstance(field, int):
                    raw = line.split()[field]
                else:
                    record = json.loads(line)
                    raw = record[field]
                values.append(_parse_time(raw, f"{path}: line {line_number} time_field"))
            except (IndexError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Setting 'time_field' could not read {path} line {line_number}; "
                    "expected a valid "
                    "field; for example time_field: 0."
                ) from exc
    return sorted(values)


def _transfer_paths(meta):
    log_path = meta.get("transfer_log")
    if not log_path:
        return None
    path = Path(log_path)
    if not path.exists():
        return set()
    return {line.strip().split()[-1] for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()}


def _check(code, dataset, explanation, path=None):
    result = {"code": code, "dataset": dataset, "explanation": explanation}
    if path is not None:
        result["path"] = path
    return result


def scan(root, expected, cruise_meta):
    """Scan *root*, append file observations, and return readiness checks."""
    _validate_expected(expected)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    start = _parse_time(cruise_meta.get("start"), "cruise_meta.start")
    end = _parse_time(cruise_meta.get("end"), "cruise_meta.end")
    now = _parse_time(cruise_meta.get("now", datetime.now(timezone.utc).isoformat()),
                      "cruise_meta.now")
    effective_end = min(end, now)
    cache_path = root / ".archive_ready_cache.json"
    old_cache = _read_cache(cache_path)
    new_cache = dict(old_cache)
    transfers = _transfer_paths(cruise_meta)
    manifest_path = root / "manifest.jsonl"
    result = {"generated_at": now.isoformat(), "datasets": [], "checks": []}
    if not cruise_meta.get("cruise_id"):
        result["checks"].append(_check("missing_metadata", None, "Cruise id is missing."))
    if not cruise_meta.get("ports"):
        result["checks"].append(_check("missing_metadata", None, "Cruise ports are missing."))

    with manifest_path.open("a", encoding="utf-8") as manifest:
        for dataset in expected["datasets"]:
            paths = [Path(value) for value in glob.glob(str(root / dataset["glob"]))]
            paths = sorted(path for path in paths if path.is_file() and path != manifest_path)
            entry = {"name": dataset["name"], "files": []}
            if dataset["required"] and not paths:
                result["checks"].append(_check(
                    "required_absent", dataset["name"], "Required dataset has no matching files."
                ))
            all_times = []
            naming = re.compile(dataset.get("filename_date_pattern", r".*"))
            for path in paths:
                relative = str(path.relative_to(root))
                stat = path.stat()
                signature = f"{stat.st_mtime_ns}:{stat.st_size}"
                cached = old_cache.get(relative, {})
                checksum = (cached.get("sha256") if cached.get("signature") == signature
                            else _hash(path))
                if cached.get("sha256") and cached["sha256"] != checksum:
                    result["checks"].append(_check(
                        "checksum_changed", dataset["name"],
                        "A closed file changed checksum and must be investigated.", relative
                    ))
                new_cache[relative] = {"signature": signature, "sha256": checksum}
                times = _timestamps(path, dataset.get("time_field", 0))
                all_times.extend(times)
                cadence = dataset["cadence_seconds"]
                gaps = [{"start": left.isoformat(), "end": right.isoformat(),
                         "seconds": (right - left).total_seconds()}
                        for left, right in zip(times, times[1:])
                        if (right - left).total_seconds() > 3 * cadence]
                transferred = (None if transfers is None
                               else relative in transfers or str(path) in transfers)
                file_entry = {
                    "path": relative, "size": stat.st_size, "sha256": checksum,
                    "first_timestamp": times[0].isoformat() if times else None,
                    "last_timestamp": times[-1].isoformat() if times else None,
                    "record_count": len(times), "gaps": gaps,
                    "config_version": cruise_meta.get("config_version"),
                    "parser": dataset.get("parser", "delimited"), "transferred": transferred,
                }
                entry["files"].append(file_entry)
                manifest.write(json.dumps(file_entry, sort_keys=True) + "\n")
                if not naming.search(path.name):
                    result["checks"].append(_check(
                        "inconsistent_naming", dataset["name"],
                        "File name does not match the dataset date pattern.", relative
                    ))
                if any(value < start or value > end for value in times):
                    result["checks"].append(_check(
                        "outside_cruise_dates", dataset["name"],
                        "File contains timestamps outside the cruise dates.", relative
                    ))
            if all_times and effective_end > start:
                covered_start = max(start, min(all_times))
                covered_end = min(effective_end, max(all_times))
                seconds = max(0, (covered_end - covered_start).total_seconds())
                total = (effective_end - start).total_seconds()
                coverage = round(100 * seconds / total, 2)
            else:
                coverage = 0.0
            entry["coverage_percent"] = coverage
            if paths and coverage < 95:
                result["checks"].append(_check(
                    "coverage_under_95", dataset["name"],
                    f"Coverage is {coverage:.2f} percent, below the required 95 percent."
                ))
            result["datasets"].append(entry)
    cache_path.write_text(json.dumps(new_cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
