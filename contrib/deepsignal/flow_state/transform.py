"""Tag sensor values with the content flowing through their valves."""

import logging
from datetime import datetime, timezone

from logger.transforms.transform import Transform


def _config_error(setting, value, expected, example):
    raise ValueError("%s saw %r; expected %s; for example %s" %
                     (setting, value, expected, example))


def _timestamp(value, setting="timestamp"):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        return float(value)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            _config_error(setting, value, "an ISO 8601 timestamp",
                          "2026-11-18T00:00:00Z")
    else:
        _config_error(setting, value, "an ISO 8601 timestamp",
                      "2026-11-18T00:00:00Z")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


class FlowStateTransform(Transform):
    """Add flow state and state-age fields without replacing input values."""

    def __init__(self, valves):
        super().__init__()
        if not isinstance(valves, list) or not valves:
            _config_error("valves", valves, "a non-empty list", "[{...}]")
        self.valves = [self._validate_valve(valve) for valve in valves]

    @staticmethod
    def _positive_number(name, value):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            _config_error(name, value, "a number greater than 0", "10")
        return float(value)

    def _validate_valve(self, source):
        if not isinstance(source, dict):
            _config_error("valve", source, "a mapping", "{id: filter_valve}")
        valve = dict(source)
        valve_id = valve.get("id")
        if not isinstance(valve_id, str) or not valve_id:
            _config_error("id", valve_id, "a non-empty string", "filter_valve")
        tags = valve.get("tags_fields")
        if (not isinstance(tags, list) or not tags or
                not all(isinstance(item, str) and item for item in tags)):
            _config_error("tags_fields", tags, "a non-empty list of field names",
                          "[TSG_Temp, TSG_Cond]")
        mode = valve.get("mode")
        if mode not in ("schedule", "field"):
            _config_error("mode", mode, "schedule or field", "schedule")
        valve["_seen_unknown"] = set()
        valve["_state"] = None
        valve["_switch_time"] = None
        if mode == "schedule":
            schedule = valve.get("schedule")
            if not isinstance(schedule, dict):
                _config_error("schedule", schedule, "a mapping", "{anchor: ...}")
            schedule = dict(schedule)
            schedule["_anchor"] = _timestamp(schedule.get("anchor"), "anchor")
            opened = self._positive_number(
                "open_minutes", schedule.get("open_minutes")) * 60
            closed = self._positive_number(
                "closed_minutes", schedule.get("closed_minutes")) * 60
            transition = schedule.get("transition_seconds", 0)
            if (not isinstance(transition, (int, float)) or
                    isinstance(transition, bool) or transition < 0):
                _config_error("transition_seconds", transition,
                              "a number 0 or greater", "90")
            if transition > min(opened, closed):
                _config_error("transition_seconds", transition,
                              "no longer than either schedule phase", "90")
            for name in ("open_content", "closed_content"):
                if not isinstance(schedule.get(name), str) or not schedule[name]:
                    _config_error(name, schedule.get(name), "a non-empty string",
                                  "seawater")
            schedule["_open"] = opened
            schedule["_closed"] = closed
            schedule["_transition"] = float(transition)
            valve["schedule"] = schedule
        else:
            state_field = valve.get("state_field")
            if not isinstance(state_field, str) or not state_field:
                _config_error("state_field", state_field, "a field name",
                              "valve_state")
            values = valve.get("values")
            if not isinstance(values, dict) or not values:
                _config_error("values", values, "a non-empty mapping",
                              "{1: seawater, 0: filtered}")
            transition = valve.get("transition_seconds", 0)
            if (not isinstance(transition, (int, float)) or
                    isinstance(transition, bool) or transition < 0):
                _config_error("transition_seconds", transition,
                              "a number 0 or greater", "90")
            valve["transition_seconds"] = float(transition)
        return valve

    @staticmethod
    def _parts(record):
        if isinstance(record, dict):
            return record.get("timestamp"), record.get("fields")
        return getattr(record, "timestamp", None), getattr(record, "fields", None)

    def _scheduled_state(self, valve, when):
        schedule = valve["schedule"]
        period = schedule["_open"] + schedule["_closed"]
        phase = (when - schedule["_anchor"]) % period
        if phase < schedule["_open"]:
            age = phase
            content = schedule["open_content"]
        else:
            age = phase - schedule["_open"]
            content = schedule["closed_content"]
        state = "transition" if age < schedule["_transition"] else content
        return state, age

    def _observe_field_state(self, valve, fields, when):
        state_field = valve["state_field"]
        if state_field not in fields:
            return
        observed = fields[state_field]
        if observed not in valve["values"] and observed not in valve["_seen_unknown"]:
            logging.warning("Valve %s state_field %s has unknown value %r",
                            valve["id"], state_field, observed)
            valve["_seen_unknown"].add(observed)
        if valve["_state"] is None:
            valve["_state"] = observed
            valve["_switch_time"] = when
        elif observed != valve["_state"]:
            valve["_state"] = observed
            valve["_switch_time"] = when

    def _field_state(self, valve, when):
        observed = valve["_state"]
        if observed is None or observed not in valve["values"]:
            age = 0 if valve["_switch_time"] is None else when - valve["_switch_time"]
            return "unknown", max(0, age)
        age = max(0, when - valve["_switch_time"])
        if age < valve["transition_seconds"] and valve.get("_has_switched", False):
            return "transition", age
        return valve["values"][observed], age

    def _transform_one(self, record):
        timestamp, fields = self._parts(record)
        if not isinstance(fields, dict):
            return record
        when = _timestamp(timestamp)
        for valve in self.valves:
            previous = valve["_state"]
            if valve["mode"] == "field":
                self._observe_field_state(valve, fields, when)
                if previous is not None and valve["_state"] != previous:
                    valve["_has_switched"] = True
            if not any(name in fields for name in valve["tags_fields"]):
                continue
            if valve["mode"] == "schedule":
                state, age = self._scheduled_state(valve, when)
            else:
                state, age = self._field_state(valve, when)
            prefix = valve["id"] + "_flow_state"
            fields[prefix] = state
            fields[prefix + "_age_s"] = age
        return record

    def transform(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            for item in record:
                self._transform_one(item)
            return record
        return self._transform_one(record)
