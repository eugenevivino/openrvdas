"""Content-addressed configuration history and semantic comparison tools."""

import datetime
import difflib
import hashlib
import json
import os
import tempfile

import yaml


HIGH_RISK_KINDS = {
    "source_changed", "serial_setting", "parser_changed", "writer_changed",
    "logger_removed", "calibration_changed", "units_changed",
}


def _loggers(value):
    if not isinstance(value, dict):
        return {}
    loggers = value.get("loggers", {})
    if isinstance(loggers, list):
        return {item.get("name"): item for item in loggers
                if isinstance(item, dict) and item.get("name")}
    if isinstance(loggers, dict) and loggers:
        return loggers
    if any(isinstance(item, dict) and
           ({"reader", "readers", "writer", "writers"} & set(item))
           for item in value.values()):
        return value
    return {}


def _change(kind, logger, what, before, after, risk=None):
    return {"kind": kind, "logger": logger, "what": what,
            "from": before, "to": after,
            "risk": risk or ("high" if kind in HIGH_RISK_KINDS else "low")}


def _nested(logger, section, key):
    if not isinstance(logger, dict):
        return None
    value = logger.get(section, logger.get(section + "s", {}))
    if not isinstance(value, dict):
        return None
    if key in value:
        return value[key]
    kwargs = value.get("kwargs", {})
    return kwargs.get(key) if isinstance(kwargs, dict) else None


def _reader(logger):
    if not isinstance(logger, dict):
        return None
    return logger.get("reader", logger.get("readers"))


def _components(value):
    if not value:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_components(item))
        return result
    if isinstance(value, dict):
        if "class" in value:
            return [value]
        return [{key: value[key]} for key in sorted(value)]
    return [value]


def semantic_diff(old, new):
    """Return JSON-safe, operationally meaningful differences between configs."""
    old_is_bundle = (isinstance(old, dict) and old and
                     all(os.path.isabs(str(key)) for key in old))
    new_is_bundle = (isinstance(new, dict) and new and
                     all(os.path.isabs(str(key)) for key in new))
    if old_is_bundle or new_is_bundle:
        changes = []
        old = old if old_is_bundle else {}
        new = new if new_is_bundle else {}
        for path in sorted(set(old) | set(new)):
            if path not in old:
                changes.append(_change("logger_added", None, path, None, new[path]))
            elif path not in new:
                changes.append(_change("logger_removed", None, path, old[path], None))
            else:
                changes.extend(semantic_diff(old[path], new[path]))
        return changes
    old_loggers, new_loggers = _loggers(old), _loggers(new)
    removed = set(old_loggers) - set(new_loggers)
    added = set(new_loggers) - set(old_loggers)
    changes = []

    for old_name in sorted(tuple(removed)):
        old_reader = _reader(old_loggers[old_name])
        matches = [name for name in added
                   if _reader(new_loggers[name]) == old_reader]
        if len(matches) == 1:
            new_name = matches[0]
            changes.append(_change("renamed", old_name, "logger name",
                                   old_name, new_name))
            removed.remove(old_name)
            added.remove(new_name)

    for name in sorted(removed):
        changes.append(_change("logger_removed", name, "logger",
                               old_loggers[name], None))
    for name in sorted(added):
        changes.append(_change("logger_added", name, "logger", None,
                               new_loggers[name]))

    for name in sorted(set(old_loggers) & set(new_loggers)):
        before, after = old_loggers[name], new_loggers[name]
        fields = [
            ("source_changed", "reader", "port", "reader port or host"),
            ("source_changed", "reader", "host", "reader port or host"),
            ("serial_setting", "reader", "baud", "baud"),
            ("serial_setting", "reader", "baudrate", "baud"),
            ("parser_changed", "reader", "device_type", "parser device type"),
            ("parser_changed", "reader", "class", "parser or reader class"),
            ("writer_changed", "writer", "path", "writer path"),
            ("writer_changed", "writer", "network", "writer network"),
            ("calibration_changed", "calibration", "coefficient",
             "calibration coefficient"),
            ("calibration_changed", "calibration", "scale", "calibration scale"),
        ]
        for kind, section, key, label in fields:
            left, right = _nested(before, section, key), _nested(after, section, key)
            if left != right:
                changes.append(_change(kind, name, label, left, right))
        for kind, key, label in (("mode_changed", "mode", "mode"),
                                 ("units_changed", "units", "units")):
            if before.get(key) != after.get(key):
                changes.append(_change(kind, name, label, before.get(key),
                                       after.get(key)))
        old_transforms = _components(before.get("transforms"))
        new_transforms = _components(after.get("transforms"))
        for transform in old_transforms:
            if transform not in new_transforms:
                changes.append(_change("transform_removed", name, "transform",
                                       transform, None))
        for transform in new_transforms:
            if transform not in old_transforms:
                changes.append(_change("transform_added", name, "transform",
                                       None, transform))
    return changes


def raw_diff(old, new):
    """Return a stable unified YAML diff for details without a semantic kind."""
    before = yaml.safe_dump(old, sort_keys=True).splitlines(True)
    after = yaml.safe_dump(new, sort_keys=True).splitlines(True)
    return "".join(difflib.unified_diff(before, after,
                                        fromfile="old", tofile="new"))


class ConfigHistory:
    """Append-only configuration history stored without a git dependency."""

    def __init__(self, directory="/var/lib/deepsignal/config-history/"):
        if not isinstance(directory, (str, os.PathLike)) or not str(directory):
            raise ValueError("directory saw an empty value; expected a path, "
                             "for example /var/lib/deepsignal/config-history/")
        self.directory = os.path.abspath(os.fspath(directory))
        self.history_path = os.path.join(self.directory, "history.jsonl")

    @staticmethod
    def _read_files(paths):
        documents = {}
        for path in paths:
            with open(path, "r", encoding="utf-8") as source:
                documents[os.path.abspath(path)] = yaml.safe_load(source)
        return documents

    @staticmethod
    def _payload(documents):
        return yaml.safe_dump(documents, sort_keys=True, allow_unicode=True)

    def _snapshot_path(self, version):
        return os.path.join(self.directory, version + ".yaml")

    def load(self, version):
        if isinstance(version, dict):
            return version
        candidate = self._snapshot_path(version)
        if not os.path.exists(candidate) and os.path.isfile(str(version)):
            candidate = str(version)
        with open(candidate, "r", encoding="utf-8") as source:
            return yaml.safe_load(source)

    def log(self):
        if not os.path.exists(self.history_path):
            return []
        with open(self.history_path, "r", encoding="utf-8") as source:
            return [json.loads(line) for line in source if line.strip()]

    def snapshot(self, paths, who, note):
        if not paths:
            raise ValueError("paths saw no files; expected at least one config "
                             "path, for example /etc/openrvdas/cruise.yaml")
        documents = self._read_files(paths)
        payload = self._payload(documents)
        version = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        history = self.log()
        parent = history[-1]["version"] if history else None
        differences = []
        if parent:
            differences = semantic_diff(self.load(parent), documents)
        policy_file = any("eez" in str(path).lower() or
                          "release" in str(path).lower() for path in paths)
        if (policy_file or any(item["risk"] == "high" for item in differences)) \
                and not str(note).strip():
            raise ValueError("note saw an empty value for a high-risk change; "
                             "expected a reason, for example 'GPS baud update'")
        os.makedirs(self.directory, exist_ok=True)
        destination = self._snapshot_path(version)
        if not os.path.exists(destination):
            fd, temporary = tempfile.mkstemp(dir=self.directory, prefix=".snapshot-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(payload)
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        record = {
            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "who": who, "note": note, "files": [os.path.abspath(p) for p in paths],
            "hashes": {path: hashlib.sha256(
                yaml.safe_dump(value, sort_keys=True).encode("utf-8")).hexdigest()
                       for path, value in documents.items()},
            "parent": parent, "version": version,
        }
        with open(self.history_path, "a", encoding="utf-8") as output:
            output.write(json.dumps(record, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())
        return version

    def diff(self, old, new):
        before, after = self.load(old), self.load(new)
        return {"semantic": semantic_diff(before, after),
                "raw": raw_diff(before, after)}

    def drift(self, baseline, current):
        return semantic_diff(self.load(baseline), self.load(current))


class ConfigWatcher:
    """Poll files, snapshot external edits, and return timeline records."""

    def __init__(self, history, paths):
        self.history = history
        self.paths = list(paths)
        self._fingerprint = self._current_fingerprint()

    def _current_fingerprint(self):
        digest = hashlib.sha256()
        for path in self.paths:
            with open(path, "rb") as source:
                digest.update(os.path.abspath(path).encode("utf-8"))
                digest.update(source.read())
        return digest.hexdigest()

    def poll(self):
        current = self._current_fingerprint()
        if current == self._fingerprint:
            return None
        self._fingerprint = current
        version = self.history.snapshot(self.paths, "unknown, detected",
                                        "external configuration edit detected")
        return {"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "who": "unknown, detected",
                "fields": {"event": "config_provenance", "version": version}}
