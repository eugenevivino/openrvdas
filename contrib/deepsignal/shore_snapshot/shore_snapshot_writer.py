"""Write compact, static ship snapshots for low-bandwidth transfer."""

import html
import json
import math
import os
import tempfile
from datetime import datetime

from logger.utils.formats import Python_Record
from logger.writers.writer import Writer


class ShoreSnapshotWriter(Writer):
    """Keep configured values and periodically publish JSON and SVG snapshots."""

    def __init__(self, fields, out_dir, ship, period_s=60, max_bytes=4096):
        self._validate_config(fields, out_dir, ship, period_s, max_bytes)
        super().__init__(input_format=Python_Record)
        self.fields = [dict(field) for field in fields]
        self.out_dir = out_dir
        self.ship = ship
        self.period_s = period_s
        self.max_bytes = max_bytes
        self._latest = {}
        self._last_write_time = None
        os.makedirs(self.out_dir, exist_ok=True)

    @staticmethod
    def _config_error(setting, value, expected, example):
        raise ValueError("setting '{}' saw {!r}; expected {}; for example {}"
                         .format(setting, value, expected, example))

    @classmethod
    def _validate_config(cls, fields, out_dir, ship, period_s, max_bytes):
        if not isinstance(fields, list) or not fields:
            cls._config_error("fields", fields, "a non-empty list of field mappings",
                              "[{'name': 'temp', 'label': 'Air temp', "
                              "'units': 'degC', 'decimals': 1}]")
        required = {"name", "label", "units", "decimals"}
        for index, field in enumerate(fields):
            if not isinstance(field, dict) or set(field) != required:
                cls._config_error("fields[{}]".format(index), field,
                                  "a mapping with name, label, units, and decimals",
                                  "{'name': 'temp', 'label': 'Air temp', "
                                  "'units': 'degC', 'decimals': 1}")
            if not isinstance(field["name"], str) or not field["name"]:
                cls._config_error("fields[{}].name".format(index), field["name"],
                                  "a non-empty string", "'temp'")
            if not isinstance(field["label"], str):
                cls._config_error("fields[{}].label".format(index), field["label"],
                                  "a string", "'Air temp'")
            if not isinstance(field["units"], str):
                cls._config_error("fields[{}].units".format(index), field["units"],
                                  "a string", "'degC'")
            if (not isinstance(field["decimals"], int) or
                    isinstance(field["decimals"], bool) or field["decimals"] < 0):
                cls._config_error("fields[{}].decimals".format(index), field["decimals"],
                                  "a non-negative integer", "1")
        names = [field["name"] for field in fields]
        if len(names) != len(set(names)):
            cls._config_error("fields", names, "unique field names", "['temp', 'wind']")
        if not isinstance(out_dir, (str, os.PathLike)) or not os.fspath(out_dir):
            cls._config_error("out_dir", out_dir, "a non-empty path string",
                              "'/var/lib/openrvdas/shore'")
        if not isinstance(ship, str) or not ship:
            cls._config_error("ship", ship, "a non-empty string", "'R/V Example'")
        if (not isinstance(period_s, (int, float)) or isinstance(period_s, bool) or
                not math.isfinite(period_s) or period_s <= 0):
            cls._config_error("period_s", period_s, "a positive number of seconds", "60")
        if (not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0):
            cls._config_error("max_bytes", max_bytes, "a positive integer byte count", "4096")

    @staticmethod
    def _timestamp_seconds(value):
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        raise ValueError(
            "record timestamp saw {!r}; expected a number or datetime; for example 60.0"
            .format(value))

    def write(self, record):
        """Consume one record or a list, returning None without modifying input."""
        if record is None:
            return None
        if isinstance(record, list):
            for item in record:
                self.write(item)
            return None
        if isinstance(record, dict):
            if "timestamp" not in record or not isinstance(record.get("fields"), dict):
                raise ValueError("record saw {!r}; expected timestamp and fields mapping; "
                                 "for example {{'timestamp': 60, "
                                 "'fields': {{'temp': 21.4}}}}"
                                 .format(record))
            timestamp = record["timestamp"]
            values = record["fields"]
        else:
            timestamp = getattr(record, "timestamp", None)
            values = getattr(record, "fields", None)
            if not isinstance(values, dict):
                raise ValueError("record saw {!r}; expected a DASRecord or record mapping; "
                                 "for example {{'timestamp': 60, 'fields': {{}}}}"
                                 .format(record))
        record_time = self._timestamp_seconds(timestamp)
        for field in self.fields:
            name = field["name"]
            if name in values:
                self._latest[name] = {
                    "value": values[name],
                    "time": record_time,
                    "q": values.get(name + "_QC"),
                }
            elif name + "_QC" in values and name in self._latest:
                self._latest[name]["q"] = values[name + "_QC"]
        if (self._last_write_time is None or
                record_time >= self._last_write_time + self.period_s):
            self._publish(timestamp, record_time)
            self._last_write_time = record_time
        return None

    @staticmethod
    def _rounded(value, decimals):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(value, decimals)
        return value

    def _field_rows(self, record_time):
        rows = []
        for config in self.fields:
            latest = self._latest.get(config["name"])
            rows.append({
                "n": config["name"],
                "v": (self._rounded(latest["value"], config["decimals"])
                      if latest else None),
                "u": config["units"],
                "age_s": (round(max(0, record_time - latest["time"])) if latest else None),
                "q": latest["q"] if latest else None,
            })
        return rows

    def _json_bytes(self, timestamp, rows):
        document = {"ship": self.ship, "time": timestamp, "fields": rows}
        encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        dropped = 0
        while len(encoded) > self.max_bytes and document["fields"]:
            document["fields"].pop()
            dropped += 1
            document["truncated"] = dropped
            encoded = json.dumps(document, separators=(",", ":"),
                                 ensure_ascii=False).encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise ValueError("max_bytes saw {}; expected enough bytes for snapshot metadata; "
                             "for example 4096".format(self.max_bytes))
        return encoded

    def _svg_bytes(self, timestamp, record_time, rows):
        lines = []
        for config, row in zip(self.fields, rows):
            label = html.escape(config["label"])
            units = html.escape(config["units"])
            value = "missing" if row["v"] is None else html.escape(str(row["v"]))
            if row["age_s"] is None:
                status = "missing"
            elif row["age_s"] > 3 * self.period_s:
                status = "STALE, {} s".format(row["age_s"])
            else:
                status = "{} s".format(row["age_s"])
            lines.append("{} {} {}, {}".format(label, value, units, status))
        height = 76 + 24 * len(lines)
        text = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="{}" '
            'viewBox="0 0 640 {}">'.format(height, height),
            '<rect width="640" height="100%" fill="#17212b"/>',
            '<g fill="#f4f7fa" font-family="sans-serif" font-size="16">',
            '<text x="20" y="28" font-size="20">{}</text>'.format(html.escape(self.ship)),
            '<text x="20" y="52">{}</text>'.format(html.escape(str(timestamp))),
        ]
        for index, line in enumerate(lines):
            text.append('<text x="20" y="{}">{}</text>'.format(76 + index * 24, line))
        text.extend(["</g>", "</svg>"])
        return "".join(text).encode("utf-8")

    def _publish(self, timestamp, record_time):
        rows = self._field_rows(record_time)
        self._atomic_write("snapshot.json", self._json_bytes(timestamp, rows))
        self._atomic_write("snapshot.svg", self._svg_bytes(timestamp, record_time, rows))

    def _atomic_write(self, filename, content):
        destination = os.path.join(self.out_dir, filename)
        descriptor, temporary = tempfile.mkstemp(
            prefix="." + filename + ".", dir=self.out_dir)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
