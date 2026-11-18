"""Dependency-aware stream health evaluation and transition tracking."""

import copy
import datetime
import os
from collections import defaultdict, deque

import yaml


STAGES = ("sensor", "endpoint", "raw_traffic", "parser", "time",
          "calibration", "derived", "store")
STATES = ("OK", "DEGRADED", "FAILED", "UNKNOWN", "OFF")


def _config_error(setting, value, expected, example):
    raise ValueError("Setting %s saw %r; expected %s; for example %s."
                     % (setting, value, expected, example))


def _validated(cfg):
    if not isinstance(cfg, dict):
        _config_error("config", cfg, "a mapping", "streams: {}")
    streams = cfg.get("streams")
    if not isinstance(streams, dict) or not streams:
        _config_error("streams", streams, "a non-empty mapping",
                      "streams: {met: {logger: met_logger, key_fields: [wind]}}")
    for name, stream in streams.items():
        if not isinstance(stream, dict):
            _config_error("streams.%s" % name, stream, "a mapping",
                          "%s: {logger: met_logger, key_fields: [wind]}" % name)
        if not isinstance(stream.get("logger"), str) or not stream["logger"]:
            _config_error("streams.%s.logger" % name, stream.get("logger"),
                          "a non-empty string", "logger: met_logger")
        fields = stream.get("key_fields")
        if not isinstance(fields, list) or not all(isinstance(v, str) for v in fields):
            _config_error("streams.%s.key_fields" % name, fields,
                          "a list of field names", "key_fields: [wind_speed]")
        period = stream.get("expected_period_s", "learned")
        if period != "learned" and (not isinstance(period, (int, float)) or period <= 0):
            _config_error("streams.%s.expected_period_s" % name, period,
                          "a positive number or 'learned'", "expected_period_s: 1")
    return cfg


def load_config(path):
    """Load and validate a hand-edited YAML chain configuration."""
    with open(path, "r", encoding="utf-8") as stream:
        return _validated(yaml.safe_load(stream))


def describe_chain(cfg):
    """Return a JSON-safe description for setup tools."""
    cfg = _validated(cfg)
    return {
        "stages": list(STAGES),
        "streams": {
            name: {
                "logger": stream["logger"],
                "key_fields": list(stream["key_fields"]),
                "affected_outputs": list(stream.get("derived", [])),
            }
            for name, stream in cfg["streams"].items()
        },
    }


def _seconds(value):
    if isinstance(value, datetime.datetime):
        return value.timestamp()
    return float(value)


def _stage(state, since, evidence):
    if state not in STATES:
        state = "UNKNOWN"
        evidence = "Unrecognized state was reported"
    if isinstance(since, datetime.datetime):
        since = since.isoformat()
    return {"state": state, "since": since, "evidence": str(evidence or "")}


def _endpoint_stage(endpoint, now):
    if not endpoint:
        return _stage("OFF", None, "No endpoint health source configured")
    if isinstance(endpoint, str) and ":" not in endpoint:
        if os.path.exists(endpoint):
            return _stage("OK", now, "Endpoint path exists: %s" % endpoint)
        return _stage("UNKNOWN", now, "Endpoint path is missing: %s" % endpoint)
    return _stage("UNKNOWN", now, "Host endpoint is not probed: %s" % endpoint)


def _store_stage(path, now):
    if not path:
        return _stage("OFF", None, "No store health source configured")
    if not os.path.isdir(path):
        return _stage("UNKNOWN", now, "Store directory is missing: %s" % path)
    files = [os.path.join(path, item) for item in os.listdir(path)]
    files = [item for item in files if os.path.isfile(item)]
    if not files:
        return _stage("UNKNOWN", now, "Store directory contains no files")
    newest = max(files, key=os.path.getmtime)
    return _stage("OK", now, "Newest store file: %s" % os.path.basename(newest))


def evaluate(cfg, snapshot, now):
    """Evaluate all stream stages without changing the configuration or input."""
    cfg = _validated(cfg)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    results = {}
    for name, stream_cfg in cfg["streams"].items():
        facts = snapshot.get(name, {})
        facts = facts if isinstance(facts, dict) else {}
        supplied = facts.get("stages", {})
        supplied = supplied if isinstance(supplied, dict) else {}
        stages = {}
        for stage_name in STAGES:
            fact = supplied.get(stage_name)
            if isinstance(fact, dict):
                stages[stage_name] = _stage(
                    str(fact.get("state", "UNKNOWN")).upper(),
                    fact.get("since", now), fact.get("evidence", ""))
            elif stage_name == "endpoint":
                stages[stage_name] = _endpoint_stage(stream_cfg.get("endpoint"), now)
            elif stage_name == "store":
                stages[stage_name] = _store_stage(stream_cfg.get("store"), now)
            elif stage_name in ("time", "calibration") and stage_name not in stream_cfg:
                stages[stage_name] = _stage(
                    "OFF", None, "No %s health source configured" % stage_name)
            else:
                stages[stage_name] = _stage("UNKNOWN", now, "No stage evidence received")

        root = next((stage_name for stage_name in STAGES
                     if stages[stage_name]["state"] not in ("OK", "OFF")), None)
        if root:
            root_index = STAGES.index(root)
            for later in STAGES[root_index + 1:]:
                stages[later]["affected"] = True
        results[name] = {
            "stages": stages,
            "root": root,
            "affected_outputs": (list(stream_cfg.get("derived", [])) if root else []),
        }
    return results


class TransitionTracker:
    """Apply hold-time hysteresis and a per-stream transition rate cap."""

    def __init__(self, hold_s=10, rate_cap=20, rate_window_s=60):
        self.hold_s = hold_s
        self.rate_cap = rate_cap
        self.rate_window_s = rate_window_s
        self._stable = {}
        self._pending = {}
        self._emitted = defaultdict(deque)

    def update(self, stream, stage, state, at, evidence):
        key = (stream, stage)
        state = state.upper()
        if state not in STATES:
            raise ValueError("State saw %r; expected one of %s; for example 'OK'."
                             % (state, ", ".join(STATES)))
        if key not in self._stable:
            self._stable[key] = state
            return []
        if state == self._stable[key]:
            self._pending.pop(key, None)
            return []
        pending = self._pending.get(key)
        if not pending or pending[0] != state:
            self._pending[key] = (state, at, evidence)
            if self.hold_s:
                return []
        pending = self._pending[key]
        if _seconds(at) - _seconds(pending[1]) < self.hold_s:
            return []
        old = self._stable[key]
        self._stable[key] = state
        self._pending.pop(key, None)
        history = self._emitted[stream]
        while history and _seconds(at) - _seconds(history[0]) >= self.rate_window_s:
            history.popleft()
        if len(history) >= self.rate_cap:
            return []
        history.append(at)
        return [{"stream": stream, "stage": stage, "from": old, "to": state,
                 "at": at.isoformat() if isinstance(at, datetime.datetime) else at,
                 "evidence": evidence}]


class StreamHealthWriter:
    """Add timeout facts and create CDS chain fields without mutating input."""

    def __init__(self, cfg, field_timeouts=None):
        self.cfg = _validated(cfg)
        self.field_timeouts = dict(field_timeouts or {})

    def transform(self, record, now=None, snapshot=None):
        if record is None:
            return None
        if isinstance(record, list):
            return [self.transform(item, now=now, snapshot=snapshot) for item in record]
        current = (datetime.datetime.now(datetime.timezone.utc).timestamp()
                   if now is None else _seconds(now))
        output = copy.deepcopy(record)
        fields = output["fields"] if isinstance(output, dict) else output.fields
        timestamp = output.get("timestamp") if isinstance(output, dict) else output.timestamp
        age = max(0, current - _seconds(timestamp))
        for field, timeout in self.field_timeouts.items():
            if field in fields and age > timeout:
                fields[field] = None
                fields["ds_age_s:%s" % field] = age
        health = evaluate(self.cfg, snapshot or {}, now if now is not None else current)
        for stream, result in health.items():
            for stage_name, stage in result["stages"].items():
                fields["ds_chain:%s:%s" % (stream, stage_name)] = stage["state"]
            fields["ds_chain:%s:root" % stream] = result["root"]
        return output
