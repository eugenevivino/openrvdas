import json
import os
import tempfile
import unittest

from contrib.deepsignal.timeline.event_timeline import EventTimeline


class EventTimelineTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.output = os.path.join(self.tempdir.name, "timeline.jsonl")
        self.timeline = EventTimeline(self.output)

    def fixture(self, name, rows):
        path = os.path.join(self.tempdir.name, name)
        with open(path, "w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
        return path

    def test_each_jsonl_adapter_and_dedupe(self):
        cases = [
            ("transitions", "transition", {"t": "2026-11-18T10:01:00Z",
             "subject": "gps", "from": "ok", "to": "alarm"}),
            ("history", "config", {"timestamp": "2026-11-18T10:02:00Z",
             "logger": "gps", "summary": "config loaded", "ref": "cfg-1"}),
            ("init_audit", "init", {"time": "2026-11-18T10:03:00Z",
             "instrument": "ctd", "message": "initialized"}),
            ("eez_audit", "eez", {"t": "2026-11-18T10:04:00Z",
             "subject": "US", "summary": "entered"}),
            ("fixes", "fix", {"t": "2026-11-18T10:05:00Z",
             "subject": "fluorometer", "summary": "replaced cable"}),
        ]
        for source, kind, row in cases:
            path = self.fixture(source + ".jsonl", [row])
            self.assertEqual(1, self.timeline.read_jsonl(path, source, kind))
            self.assertEqual(0, self.timeline.read_jsonl(path, source, kind))
        self.assertEqual(5, len(self.timeline.query(None, None)))

    def test_cds_records_list_dict_none_and_sealog(self):
        self.assertIsNone(self.timeline.ingest_cds(None))
        record = {"timestamp": "2026-11-18T10:00:00Z", "fields": {
            "stderr:logger:gps": "timeout", "status:logger_status": "alarm"}}
        self.assertIs(record, self.timeline.ingest_cds(record))
        records = [record, {"timestamp": "2026-11-18T10:01:00Z", "fields": {
            "status:logger_status": "ok"}}]
        self.assertIs(records, self.timeline.ingest_cds(records))
        self.assertEqual(3, len(self.timeline.query(None, None, kinds=["alarm"])))
        self.assertEqual(1, self.timeline.ingest_sealog([{
            "id": 7, "timestamp": "2026-11-18T10:02:00Z",
            "event": "CTD in water", "author": "sam"}]))

    def test_order_around_ranking_notes_and_append_only(self):
        self.timeline.add("2026-11-18T10:00:00Z", "note", "operator",
                          "deck", "watch changed", "note-1")
        self.timeline.add("2026-11-18T10:00:00Z", "transition",
                          "transitions", "gps", "alarm", "tr-1")
        self.timeline.add("2026-11-18T09:59:00Z", "config", "history",
                          "gps", "baud changed", "cfg-1")
        with open(self.output, "rb") as stream:
            before = stream.read()
        self.timeline.add("2026-11-18T10:00:00Z", "note", "operator",
                          "deck", "watch changed", "note-1")
        with open(self.output, "rb") as stream:
            self.assertEqual(before, stream.read())
        ordered = self.timeline.query(None, None)
        self.assertEqual(["config", "note", "transition"],
                         [item["kind"] for item in ordered])
        around = self.timeline.around("2026-11-18T10:01:00Z", minutes=5)
        self.assertEqual(["config", "transition", "note"],
                         [item["kind"] for item in around])
        note = self.timeline.note("hello", "pat")
        self.assertEqual("pat", note["subject"])

    def test_digest_json_and_text(self):
        rows = [
            ("transition", "gps", "alarm"), ("config", "gps", "reload"),
            ("eez", "US", "entered"), ("fix", "ctd", "cable fixed"),
            ("alarm", "wind", "open problem"),
        ]
        for number, (kind, subject, summary) in enumerate(rows):
            self.timeline.add("2026-11-18T10:0%d:00Z" % number, kind,
                              "fixture", subject, summary, str(number))
        digest = self.timeline.digest("2026-11-18")
        self.assertEqual(1, len(digest["transitions"]))
        self.assertEqual(1, len(digest["open_problems"]))
        self.assertIn("config changes: 1", digest["text"])


if __name__ == "__main__":
    unittest.main()
