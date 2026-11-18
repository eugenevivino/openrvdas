"""Cross-check depth reports without communicating with ship systems."""

import math
import statistics
from datetime import datetime

from logger.transforms.transform import Transform


class DepthConsensusTransform(Transform):
    """Add deterministic depth-consensus fields to records."""

    def __init__(self, sources, threshold_pct=2.0, min_depth_m=5,
                 persist_s=60, clear_s=60, prefix="DEPTH"):
        super().__init__()
        self.sources = self._validate_sources(sources)
        self.threshold_pct = self._positive("threshold_pct", threshold_pct, "2.0")
        self.min_depth_m = self._nonnegative("min_depth_m", min_depth_m, "5")
        self.persist_s = self._nonnegative("persist_s", persist_s, "60")
        self.clear_s = self._nonnegative("clear_s", clear_s, "60")
        if not isinstance(prefix, str) or not prefix.strip():
            self._error("prefix", prefix, "a non-empty string", "DEPTH")
        self.prefix = prefix.strip()
        self._state = {name: {} for name in self.sources}
        self._condition_since = None
        self._clear_since = None
        self._alarm = False
        self._alarm_text = ""

    @staticmethod
    def _error(setting, saw, expected, example):
        raise ValueError(
            "%s saw %r; expected %s; example: %s" %
            (setting, saw, expected, example)
        )

    @classmethod
    def _number(cls, setting, value, expected, example):
        if isinstance(value, bool):
            cls._error(setting, value, expected, example)
        try:
            number = float(value)
        except (TypeError, ValueError):
            cls._error(setting, value, expected, example)
        if not math.isfinite(number):
            cls._error(setting, value, expected, example)
        return number

    @classmethod
    def _positive(cls, setting, value, example):
        number = cls._number(setting, value, "a number greater than zero", example)
        if number <= 0:
            cls._error(setting, value, "a number greater than zero", example)
        return number

    @classmethod
    def _nonnegative(cls, setting, value, example):
        number = cls._number(setting, value, "a number zero or greater", example)
        if number < 0:
            cls._error(setting, value, "a number zero or greater", example)
        return number

    @classmethod
    def _validate_sources(cls, sources):
        if not isinstance(sources, dict) or not sources:
            cls._error("sources", sources, "a non-empty mapping", "{mb: {field: MBDepth}}")
        result = {}
        for name, config in sources.items():
            setting = "sources.%s" % name
            if not isinstance(name, str) or not name or not isinstance(config, dict):
                cls._error(setting, config, "a named source mapping", "mb: {field: MBDepth}")
            field = config.get("field")
            if not isinstance(field, str) or not field:
                cls._error(setting + ".field", field, "a non-empty field name", "MB_NadirDepth")
            role = config.get("role", "sonar")
            if role not in ("sonar", "reference"):
                cls._error(setting + ".role", role, "sonar or reference", "sonar")
            result[name] = {
                "field": field,
                "offset_m": cls._number(
                    setting + ".offset_m", config.get("offset_m", 0),
                    "a finite number", "5.2"
                ),
                "max_age_s": cls._positive(
                    setting + ".max_age_s", config.get("max_age_s", 60), "10"
                ),
                "role": role,
            }
        if not any(item["role"] == "sonar" for item in result.values()):
            cls._error("sources", sources, "at least one sonar role", "mb: {role: sonar, ...}")
        return result

    @staticmethod
    def _seconds(timestamp):
        if isinstance(timestamp, datetime):
            return timestamp.timestamp()
        if isinstance(timestamp, bool):
            raise ValueError(
                "timestamp saw %r; expected a number or datetime; example: 1700000000" %
                timestamp
            )
        try:
            value = float(timestamp)
        except (TypeError, ValueError):
            raise ValueError(
                "timestamp saw %r; expected a number or datetime; example: 1700000000" % timestamp
            )
        if not math.isfinite(value):
            raise ValueError(
                "timestamp saw %r; expected a finite number; example: 1700000000" % timestamp
            )
        return value

    @staticmethod
    def _valid(value):
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number > 0 else None

    def transform(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            for item in record:
                self._transform_one(item)
            return record
        self._transform_one(record)
        return record

    def _transform_one(self, record):
        if isinstance(record, dict):
            fields = record.get("fields")
            timestamp = record.get("timestamp")
        else:
            fields = getattr(record, "fields", None)
            timestamp = getattr(record, "timestamp", None)
        if not isinstance(fields, dict):
            raise ValueError(
                "record.fields saw %r; expected a mapping; example: {'MB': 100}" % fields
            )
        now = self._seconds(timestamp)
        previous = {name: state.get("value") for name, state in self._state.items()}
        for name, config in self.sources.items():
            if config["field"] not in fields:
                continue
            raw = self._valid(fields[config["field"]])
            state = self._state[name]
            if raw is None:
                if state.get("invalid_since") is None:
                    state["invalid_since"] = now
                state["available"] = False
            else:
                state.update(value=raw + config["offset_m"], time=now,
                             available=True, invalid_since=None)

        fresh = {}
        stale = []
        for name, config in self.sources.items():
            state = self._state[name]
            if "time" not in state or now - state["time"] > config["max_age_s"]:
                stale.append(name)
            elif state.get("available"):
                fresh[name] = state["value"]

        sonars = {name: value for name, value in fresh.items()
                  if self.sources[name]["role"] == "sonar"}
        references = {name: value for name, value in fresh.items()
                      if self.sources[name]["role"] == "reference"}
        consensus = statistics.median(sonars.values()) if sonars else None
        deviations = {}
        if consensus is not None and consensus >= self.min_depth_m:
            deviations = {name: abs(value - consensus) / consensus * 100
                          for name, value in fresh.items()}
        spread = 0.0
        if len(sonars) > 1 and consensus and consensus >= self.min_depth_m:
            spread = (max(sonars.values()) - min(sonars.values())) / consensus * 100

        odd, metric, comparison, suspicious = self._diagnose(
            sonars, references, consensus, deviations, spread
        )
        condition = metric > self.threshold_pct
        clear_condition = metric < self.threshold_pct * 0.75
        text_value = sonars.get(odd) if odd else None
        alarm_text = self._text(odd, text_value, comparison, suspicious) if condition else ""
        self._update_alarm(now, condition, clear_condition, alarm_text)

        lost = []
        if sonars:
            for name, config in self.sources.items():
                if config["role"] != "sonar" or name in sonars:
                    continue
                state = self._state[name]
                since = state.get("invalid_since")
                if since is not None and now - since >= self.persist_s:
                    lost.append(name)

        steps = self._steps(previous, sonars)
        output = {
            "Consensus": consensus,
            "SpreadPct": spread if consensus is not None else None,
            "OddOne": odd or "",
            "Alarm": int(self._alarm),
            "AlarmText": self._alarm_text if self._alarm else "",
            "Stale": ",".join(stale),
            "LostBottom": ",".join(lost),
            "Step": ",".join(steps),
        }
        for name in self.sources:
            output["Dev_" + name] = deviations.get(name)
        fields.update({self.prefix + "_" + key: value for key, value in output.items()})

    def _diagnose(self, sonars, references, consensus, deviations, spread):
        if not sonars or consensus is None or consensus < self.min_depth_m:
            return None, 0, None, False
        if len(sonars) == 1 and references:
            name, value = next(iter(sonars.items()))
            reference = statistics.median(references.values())
            metric = abs(value - reference) / max(value, reference) * 100
            return name, metric, reference, True
        if len(sonars) > 1:
            if references:
                target = statistics.median(references.values())
                odd = max(sonars, key=lambda name: abs(sonars[name] - target))
                comparison = target
            else:
                odd = max(sorted(sonars), key=lambda name: deviations[name])
                comparison = consensus
            return odd, spread, comparison, False
        return None, 0, None, False

    def _steps(self, previous, sonars):
        changes = {}
        for name, value in sonars.items():
            old = previous.get(name)
            if old:
                changes[name] = abs(value - old) / old * 100
        return sorted(name for name, change in changes.items()
                      if change > 4 * self.threshold_pct and
                      all(other == name or delta <= self.threshold_pct
                          for other, delta in changes.items()))

    def _text(self, name, value, comparison, suspicious):
        label = "suspicious " if suspicious else ""
        return ("%s%s depth %.2f m differs from comparison %.2f m; threshold %.2f%%; "
                "first check transducer draft and bottom lock" %
                (label, name, value, comparison, self.threshold_pct))

    def _update_alarm(self, now, condition, clear_condition, alarm_text):
        if condition:
            self._clear_since = None
            if self._condition_since is None:
                self._condition_since = now
            if now - self._condition_since >= self.persist_s:
                self._alarm = True
                self._alarm_text = alarm_text
        else:
            self._condition_since = None
            if self._alarm and clear_condition:
                if self._clear_since is None:
                    self._clear_since = now
                if now - self._clear_since >= self.clear_s:
                    self._alarm = False
                    self._alarm_text = ""
            elif not clear_condition:
                self._clear_since = None
