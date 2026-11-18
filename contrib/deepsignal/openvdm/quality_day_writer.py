"""Write DeepSignal quality fields as daily CSV products."""

import csv
import os
from datetime import datetime, timezone

from logger.utils.formats import Python_Record
from logger.writers.writer import Writer


class QualityDayWriter(Writer):
    """Append ``_QC`` fields to per-instrument, per-UTC-day CSV files."""

    HEADER = ("timestamp", "field", "value", "flag", "reason")

    def __init__(self, root, data_id):
        if not isinstance(root, str) or not root.strip():
            raise ValueError(
                "root saw %r; expected a non-empty path, for example /data/quality" % root)
        if not isinstance(data_id, str) or not data_id.strip():
            raise ValueError("data_id saw %r; expected a non-empty name, for example ctd" % data_id)
        super().__init__(input_format=Python_Record)
        self.root = root
        self.data_id = data_id

    @staticmethod
    def _record_parts(record):
        if isinstance(record, dict):
            return record.get("timestamp"), record.get("fields", {})
        return getattr(record, "timestamp", None), getattr(record, "fields", {})

    @staticmethod
    def _timestamp_text_and_day(timestamp):
        if isinstance(timestamp, datetime):
            value = timestamp
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            value = value.astimezone(timezone.utc)
            return value.isoformat().replace("+00:00", "Z"), value.date().isoformat()
        if isinstance(timestamp, (int, float)):
            value = datetime.fromtimestamp(timestamp, timezone.utc)
            return str(timestamp), value.date().isoformat()
        if isinstance(timestamp, str):
            value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return timestamp, value.astimezone(timezone.utc).date().isoformat()
        raise ValueError(
            "timestamp saw %r; expected UTC ISO text or epoch seconds, for example "
            "2026-11-18T12:00:00Z" % timestamp)

    def write(self, record):
        if record is None:
            return None
        records = record if isinstance(record, list) else [record]
        for item in records:
            timestamp, fields = self._record_parts(item)
            timestamp_text, day = self._timestamp_text_and_day(timestamp)
            if not isinstance(fields, dict):
                raise ValueError(
                    "fields saw %r; expected a mapping, for example {'temp_QC': 1}" % fields)
            rows = []
            for quality_name, flag in fields.items():
                if not quality_name.endswith("_QC"):
                    continue
                field = quality_name[:-3]
                rows.append((timestamp_text, field, fields.get(field), flag,
                             fields.get(field + "_QC_REASON", "")))
            if rows:
                self._append(day, rows)
        return None

    def _append(self, day, rows):
        directory = os.path.join(self.root, self.data_id)
        os.makedirs(directory, exist_ok=True)
        filename = os.path.join(directory, "%s-quality-%s.csv" % (self.data_id, day))
        is_new = not os.path.exists(filename) or os.path.getsize(filename) == 0
        with open(filename, "a", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            if is_new:
                writer.writerow(self.HEADER)
            writer.writerows(rows)
