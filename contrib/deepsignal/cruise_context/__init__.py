"""Cruise metadata importers and a record tagging transform."""
import copy
import json
import os
import time
from urllib.request import Request, urlopen

try:
    from logger.transforms.transform import Transform
except ImportError:
    from openrvdas.logger.transforms.transform import Transform


def _empty():
    return {
        "cruise": {"id": None, "name": None, "description": None, "pi": None,
                   "dates": {"start": None, "end": None},
                   "ports": {"start": None, "end": None}, "location": None},
        "vessel": {"name": None, "operator": None,
                   "r2r": {"vessel_id": None, "operator_id": None,
                           "scheduler_id": None}},
        "lowering": {"id": None, "dates": {"start": None, "end": None}},
    }


def _value(data, *names):
    for name in names:
        value = data.get(name)
        if value not in (None, ""):
            return value
    return None


def from_openvdm(cfg):
    """Map an OpenVDM 2.17 cruise configuration to cruise metadata."""
    result = _empty()
    cruise = result["cruise"]
    cruise.update(id=_value(cfg, "cruise_id", "cruiseID"),
                  name=_value(cfg, "cruise_name", "cruiseName"),
                  description=_value(cfg, "cruise_description", "description"),
                  pi=_value(cfg, "chief_scientist", "pi"),
                  location=_value(cfg, "cruise_location", "location"))
    cruise["dates"].update(
        start=_value(cfg, "start_date"), end=_value(cfg, "end_date"))
    cruise["ports"].update(start=_value(cfg, "start_port"), end=_value(cfg, "end_port"))
    vessel = cfg.get("vessel") or {}
    result["vessel"].update(name=_value(vessel, "name"), operator=_value(vessel, "operator"))
    result["vessel"]["r2r"].update(
        vessel_id=_value(vessel, "r2r_vessel_id", "r2rVesselId"),
        operator_id=_value(vessel, "r2r_operator_id", "r2rOperatorId"),
        scheduler_id=_value(vessel, "r2r_scheduler_id", "r2rSchedulerId"))
    result["lowering"]["id"] = _value(cfg, "lowering_id")
    result["lowering"]["dates"].update(
        start=_value(cfg, "lowering_start_date"), end=_value(cfg, "lowering_end_date"))
    return result


def from_sealog(cruise):
    """Map one Sealog cruise response to cruise metadata."""
    result = _empty()
    result["cruise"].update(id=_value(cruise, "cruise_id"),
                            location=_value(cruise, "cruise_location"))
    result["cruise"]["dates"].update(
        start=_value(cruise, "start_ts"), end=_value(cruise, "stop_ts"))
    additional = cruise.get("cruise_additional_meta") or {}
    if isinstance(additional, dict):
        result["lowering"]["id"] = _value(additional, "lowering_id")
    return result


def fetch(source, url, token_env=None):
    """Fetch JSON once from a supported read-only endpoint."""
    if source not in ("openvdm", "sealog"):
        raise ValueError(
            "source saw %r; expected openvdm or sealog, for example openvdm" % source)
    endpoint = url.rstrip("/")
    if source == "openvdm":
        endpoint += "/api/warehouse/getCruiseConfig"
    else:
        endpoint += "/api/v1/cruises"
    headers = {}
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            raise ValueError("token_env saw unset %r; expected an environment variable containing "
                             "a JWT, for example SEALOG_TOKEN" % token_env)
        headers["Authorization"] = "Bearer " + token
    with urlopen(Request(endpoint, headers=headers, method="GET"), timeout=10) as response:
        value = json.load(response)
    if source == "sealog" and isinstance(value, list):
        return value[0] if value else {}
    return value


class CruiseContextReader(Transform):
    """Add current cruise context fields while retaining input data."""

    def __init__(self, source, url, token_env=None, interval=300, fetcher=fetch):
        super().__init__()
        if interval <= 0:
            raise ValueError(
                "interval saw %r; expected a value greater than zero, for example 300" % interval)
        self.source, self.url, self.token_env = source, url, token_env
        self.interval, self.fetcher = interval, fetcher
        self._last_poll = None
        self._context = None
        self._stale = False

    def __repr__(self):
        return "%s(source=%r, url=%r, interval=%r)" % (
            type(self).__name__, self.source, self.url, self.interval)

    def _poll(self, force=False):
        now = time.monotonic()
        if not force and self._last_poll is not None and now - self._last_poll < self.interval:
            return
        self._last_poll = now
        try:
            raw = self.fetcher(self.source, self.url, self.token_env)
            self._context = from_openvdm(raw) if self.source == "openvdm" else from_sealog(raw)
            self._stale = False
        except (OSError, ValueError, json.JSONDecodeError):
            if self._context is None:
                raise
            self._stale = True

    def transform(self, record, force=False):
        if record is None:
            return None
        if isinstance(record, list):
            return [self.transform(item, force=force) for item in record]
        self._poll(force)
        result = copy.deepcopy(record)
        fields = result["fields"] if isinstance(result, dict) else result.fields
        fields["cruise_id"] = self._context["cruise"]["id"]
        fields["lowering_id"] = self._context["lowering"]["id"]
        end = self._context["cruise"]["dates"]["end"]
        fields["cruise_active"] = end is None
        fields["cruise_context_stale"] = self._stale
        return result
