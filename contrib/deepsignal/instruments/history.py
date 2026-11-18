"""Plain-YAML instrument history registry and consistency checker."""

import datetime

import yaml


UTC = datetime.timezone.utc
EVENT_TYPES = {
    "install", "remove", "calibration", "firmware", "repair", "move",
    "clock_source", "software_version", "note", "cleaning", "pump_off",
    "pump_on", "valve", "power_cycle", "swap",
}
BREAK_TYPES = {
    "install", "remove", "swap", "calibration", "cleaning", "repair",
    "firmware", "power_cycle", "pump_off", "pump_on", "valve",
}


def _validation(identifier, setting, saw, expected, example):
    raise ValueError(
        f"instrument {identifier}, setting {setting}, saw {saw}, expected {expected}; "
        f"for example: {example}")


def _time(value, identifier="<query>", setting="time"):
    """Return an aware UTC datetime without guessing omitted values."""
    original = value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.datetime.fromtimestamp(value, UTC)
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            _validation(identifier, setting, repr(original), "a UTC time",
                        "2026-03-01T00:00Z")
        return value.astimezone(UTC)
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time(), UTC)
    if isinstance(value, str):
        try:
            if len(value) == 10:
                return datetime.datetime.combine(
                    datetime.date.fromisoformat(value), datetime.time(), UTC)
            parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() != datetime.timedelta(0):
                raise ValueError
            return parsed.astimezone(UTC)
        except ValueError:
            pass
    _validation(identifier, setting, repr(original), "a UTC ISO 8601 time",
                "2026-03-01T00:00Z")


class InstrumentHistory:
    """An immutable-in-practice view of instrument metadata events."""

    def __init__(self, instruments):
        self.instruments = instruments
        self._by_id = {item["id"]: item for item in instruments}

    @classmethod
    def load(cls, path):
        """Safely load an instrument registry from *path*."""
        with open(path, encoding="utf-8") as source:
            return cls.from_dict(yaml.safe_load(source))

    @classmethod
    def from_dict(cls, data):
        """Validate and construct a registry from decoded YAML data."""
        if not isinstance(data, dict) or not isinstance(data.get("instruments"), list):
            _validation("<unknown>", "instruments",
                        repr(data.get("instruments") if isinstance(data, dict) else data),
                        "a list", "instruments: []")
        instruments = []
        identifiers = set()
        for raw in data["instruments"]:
            if not isinstance(raw, dict):
                _validation("<unknown>", "instrument", repr(raw), "a mapping",
                            "- id: tsg1")
            identifier = raw.get("id", "<unknown>")
            required = ("id", "make", "model", "serial", "fields", "events")
            for setting in required:
                if setting not in raw:
                    _validation(identifier, setting, "missing", "a value",
                                f"{setting}: value")
            if not isinstance(raw["id"], str) or not raw["id"]:
                _validation(identifier, "id", repr(raw["id"]), "a non-empty string",
                            "id: tsg1")
            if identifier in identifiers:
                _validation(identifier, "id", repr(identifier), "a unique id",
                            "id: tsg2")
            identifiers.add(identifier)
            if not isinstance(raw["serial"], str):
                _validation(identifier, "serial", raw["serial"], "a string",
                            'serial: "0231"')
            if not isinstance(raw["fields"], list) or not all(
                    isinstance(field, str) for field in raw["fields"]):
                _validation(identifier, "fields", repr(raw["fields"]),
                            "a list of field names", "fields: [TSG_Temp]")
            if not isinstance(raw["events"], list):
                _validation(identifier, "events", repr(raw["events"]), "a list",
                            "events: []")
            item = dict(raw)
            item["events"] = []
            for number, raw_event in enumerate(raw["events"], 1):
                if not isinstance(raw_event, dict):
                    _validation(identifier, f"event {number}", repr(raw_event),
                                "a mapping", "- {time: 2026-03-01, type: install}")
                for setting in ("time", "type"):
                    if setting not in raw_event:
                        _validation(identifier, f"event {setting}", "missing", "a value",
                                    f"{setting}: install")
                if not isinstance(raw_event["type"], str):
                    _validation(identifier, "event type", repr(raw_event["type"]),
                                "a string", "type: install")
                parsed = dict(raw_event)
                parsed["time"] = _time(raw_event["time"], identifier, "event time")
                if "valid_until" in parsed:
                    parsed["valid_until"] = _time(
                        parsed["valid_until"], identifier, "valid_until")
                parsed["_order"] = number
                item["events"].append(parsed)
            shares = raw.get("shares", [])
            if not isinstance(shares, list):
                _validation(identifier, "shares", repr(shares), "a list",
                            "shares: [{id: tsg2, what: intake}]")
            instruments.append(item)
        return cls(instruments)

    def state_at(self, instrument_id, t):
        """Return the state of *instrument_id* at time *t*."""
        item = self._by_id.get(instrument_id)
        if item is None:
            return None
        query_time = _time(t)
        state = {"id": instrument_id, "serial": item["serial"], "firmware": None,
                 "position": None, "calibration": None, "installed": False,
                 "fields": list(item["fields"])}
        events = sorted(item["events"], key=lambda value: (value["time"], value["_order"]))
        for current in events:
            if current["time"] > query_time:
                break
            event_type = current["type"]
            if event_type in ("install", "swap"):
                state["installed"] = True
                if "position" in current:
                    state["position"] = current["position"]
            elif event_type == "remove":
                state["installed"] = False
            elif event_type == "move":
                state["position"] = current.get("position")
            elif event_type == "firmware":
                state["firmware"] = current.get("version")
            elif event_type == "calibration":
                state["calibration"] = self._public_event(current)
        return state

    @staticmethod
    def _public_event(event):
        return {key: value for key, value in event.items() if key != "_order"}

    def instrument_for_field(self, field, t):
        """Return the installed instrument state feeding *field*, if unique."""
        matches = [self.state_at(item["id"], t) for item in self.instruments
                   if field in item["fields"]]
        matches = [state for state in matches if state["installed"]]
        return matches[0] if len(matches) == 1 else None

    def calibration_for_field(self, field, t):
        """Return the active calibration for an installed field."""
        state = self.instrument_for_field(field, t)
        return state["calibration"] if state else None

    def segment_breaks(self, field, start, end):
        """Return forced drift-segment boundaries in inclusive range."""
        start_time, end_time = _time(start), _time(end)
        return sorted({current["time"] for item in self.instruments
                       if field in item["fields"] for current in item["events"]
                       if current["type"] in BREAK_TYPES
                       and start_time <= current["time"] <= end_time})

    def check(self, t=None):
        """Return errors and warnings found in the registry."""
        now = _time(t) if t is not None else datetime.datetime.now(UTC)
        findings = []

        def add(level, identifier, message):
            findings.append({"level": level, "instrument": identifier,
                             "message": message})

        all_times = set()
        for item in self.instruments:
            identifier = item["id"]
            times = [current["time"] for current in item["events"]]
            all_times.update(times)
            if times != sorted(times):
                add("error", identifier, "events are out of time order")
            installed = False
            has_calibration = False
            for current in sorted(item["events"],
                                  key=lambda value: (value["time"], value["_order"])):
                event_type = current["type"]
                if event_type not in EVENT_TYPES:
                    add("error", identifier, f"unknown event type {event_type}")
                if event_type in ("calibration", "firmware") and not installed:
                    add("error", identifier,
                        f"{event_type} event at {current['time'].isoformat()} while not installed")
                if event_type in ("install", "swap"):
                    if installed and not has_calibration:
                        add("warning", identifier, "installed with no calibration")
                    installed, has_calibration = True, False
                elif event_type == "remove":
                    if installed and not has_calibration:
                        add("warning", identifier, "installed with no calibration")
                    installed = False
                elif event_type == "calibration":
                    has_calibration = True
                    expiry = current.get("valid_until")
                    if expiry is not None and expiry < now:
                        add("warning", identifier,
                            f"calibration {current.get('cal_id', '<unknown>')} expired")
                    for field in current.get("coefficients", {}):
                        if field not in item["fields"]:
                            add("error", identifier,
                                f"calibration coefficients field {field} does not list "
                                "on instrument")
            if installed and not has_calibration:
                add("warning", identifier, "installed with no calibration")
            for share in item.get("shares", []):
                target = share.get("id") if isinstance(share, dict) else None
                if target not in self._by_id:
                    add("warning", identifier,
                        f"shares references missing instrument {target}")

        for moment in sorted(all_times):
            active = [self.state_at(item["id"], moment) for item in self.instruments]
            active = [state for state in active if state["installed"]]
            for index, left in enumerate(active):
                for right in active[index + 1:]:
                    if left["serial"] == right["serial"]:
                        add("error", left["id"],
                            f"same serial {left['serial']} installed in two places at once")
                    for field in set(left["fields"]) & set(right["fields"]):
                        add("error", left["id"],
                            f"field {field} fed by two installed instruments at once")
        # A contradiction may persist over many boundaries; keep output readable.
        unique = []
        seen = set()
        for finding in findings:
            key = tuple(finding.values())
            if key not in seen:
                seen.add(key)
                unique.append(finding)
        return unique
