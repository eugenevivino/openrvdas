"""Append-only event timeline for operational and science events."""

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

try:
    from logger.transforms.transform import Transform
except ImportError:
    from openrvdas.logger.transforms.transform import Transform


def _iso(value):
    """Return a consistently sortable UTC ISO timestamp."""
    if isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as error:
            raise ValueError("timestamp saw %r; expected ISO 8601 or Unix seconds, "
                             "for example 2026-11-18T10:00:00Z" % value) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class EventTimeline:
    """Store, import, and query a unified append-only timeline."""

    def __init__(self, path):
        if not isinstance(path, (str, os.PathLike)) or not str(path):
            raise ValueError("path saw %r; expected a non-empty file path, "
                             "for example /var/log/openrvdas/timeline.jsonl" % path)
        self.path = os.fspath(path)
        self._events = []
        self._ids = set()
        self._cds_values = {}
        if os.path.exists(self.path):
            self._load()

    def _load(self):
        with open(self.path, encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    message = ("timeline line %d saw invalid JSON; expected one JSON object "
                               "per line, for example {\"t\": \"2026-11-18T10:00:00Z\"}")
                    raise ValueError(message % line_number) from error
                self._events.append(event)
                self._ids.add(event["id"])

    def add(self, timestamp, kind, source, subject, summary, ref):
        """Append an event unless its source/ref identity was already seen."""
        values = {"kind": kind, "source": source, "subject": subject,
                  "summary": summary, "ref": ref}
        for setting, value in values.items():
            if value is None or not str(value):
                examples = {"kind": "alarm", "source": "cds", "subject": "gps",
                            "summary": "timeout", "ref": "event-42"}
                raise ValueError("%s saw %r; expected a non-empty value, for example %s"
                                 % (setting, value, examples[setting]))
        identity = hashlib.sha256((str(source) + str(ref)).encode("utf-8")).hexdigest()
        if identity in self._ids:
            return None
        event = {"t": _iso(timestamp), "kind": str(kind), "source": str(source),
                 "subject": str(subject), "summary": str(summary), "ref": str(ref),
                 "id": identity}
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        self._events.append(event)
        self._ids.add(identity)
        return event

    def read_jsonl(self, path, source, kind):
        """Import a supported JSONL audit or history file."""
        count = 0
        with open(path, encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError("%s line %d saw invalid JSON; expected one JSON object "
                                     "per line, for example {\"t\": \"2026-11-18T10:00:00Z\"}"
                                     % (source, line_number)) from error
                timestamp = row.get("t", row.get("timestamp", row.get("time")))
                subject = row.get("subject", row.get("logger", row.get("instrument", source)))
                summary = row.get("summary", row.get("message"))
                if summary is None and "from" in row and "to" in row:
                    summary = "%s to %s" % (row["from"], row["to"])
                ref = row.get("ref", row.get("id"))
                if ref is None:
                    ref = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                if self.add(timestamp, kind, source, subject, summary, ref):
                    count += 1
        return count

    def ingest_cds(self, records):
        """Observe CDS status fields without changing the incoming value."""
        if records is None:
            return None
        items = records if isinstance(records, list) else [records]
        for record in items:
            timestamp = (record.get("timestamp") if isinstance(record, dict)
                         else record.timestamp)
            fields = record.get("fields", {}) if isinstance(record, dict) else record.fields
            for field, value in fields.items():
                if not (field.startswith("stderr:logger:") or field == "status:logger_status"):
                    continue
                previous = self._cds_values.get(field, object())
                self._cds_values[field] = value
                if previous == value:
                    continue
                subject = field.split(":")[-1]
                ref = "%s:%s:%s" % (_iso(timestamp), field, value)
                self.add(timestamp, "alarm", "cds", subject, str(value), ref)
        return records

    def ingest_sealog(self, events):
        """Import events already retrieved from Sealog."""
        count = 0
        for row in events:
            event = self.add(row.get("timestamp", row.get("t")), "science", "sealog",
                             row.get("subject", row.get("author", "science")),
                             row.get("event", row.get("summary")), row.get("id"))
            count += event is not None
        return count

    def fetch_sealog(self, url, token_env="SEALOG_TOKEN", opener=urlopen):
        """Read Sealog JSON through an authenticated, read-only GET."""
        token = os.environ.get(token_env)
        if not token:
            raise ValueError("%s saw no value; expected an environment token, for example "
                             "export %s=read-only-token" % (token_env, token_env))
        request = Request(url, headers={"Authorization": "Bearer " + token}, method="GET")
        with opener(request) as response:
            return self.ingest_sealog(json.load(response))

    def note(self, text, who, timestamp=None):
        """Append an operator note."""
        timestamp = timestamp or datetime.now(timezone.utc)
        ref = hashlib.sha256((str(timestamp) + str(who) + str(text)).encode()).hexdigest()
        return self.add(timestamp, "note", "operator", who, text, ref)

    def query(self, start, end, kinds=None, subject=None):
        """Return matching events in chronological order, ties by source."""
        start_value = _iso(start) if start is not None else None
        end_value = _iso(end) if end is not None else None
        wanted = set(kinds) if kinds else None
        result = [event.copy() for event in self._events
                  if (start_value is None or event["t"] >= start_value)
                  and (end_value is None or event["t"] <= end_value)
                  and (wanted is None or event["kind"] in wanted)
                  and (subject is None or event["subject"] == subject)]
        return sorted(result, key=lambda event: (event["t"], event["source"]))

    def around(self, timestamp, minutes=30):
        """Rank nearby evidence with config and transition events first."""
        center = datetime.fromisoformat(_iso(timestamp).replace("Z", "+00:00"))
        events = self.query(center - timedelta(minutes=minutes),
                            center + timedelta(minutes=minutes))
        priority = {"config": 0, "transition": 1}
        return sorted(events, key=lambda event: (
            priority.get(event["kind"], 2), event["t"], event["source"]))

    def digest(self, day):
        """Build JSON-ready sections and a plain-text daily summary."""
        day_text = day.isoformat() if isinstance(day, date) else str(day)
        events = self.query(day_text + "T00:00:00Z", day_text + "T23:59:59.999999Z")
        names = {"transitions": "transition", "open_problems": "alarm",
                 "config_changes": "config", "eez": "eez", "fixes": "fix"}
        result = {name: [event for event in events if event["kind"] == kind]
                  for name, kind in names.items()}
        result["day"] = day_text
        result["text"] = "\n".join(["Timeline digest " + day_text] + [
            "%s: %d" % (name.replace("_", " "), len(result[name])) for name in names])
        return result


class EventTimelineTransform(Transform):
    """OpenRVDAS transform that observes CDS records and passes them through."""

    def __init__(self, path, **kwargs):
        super().__init__(**kwargs)
        self.timeline = EventTimeline(path)

    def transform(self, record):
        return self.timeline.ingest_cds(record)
