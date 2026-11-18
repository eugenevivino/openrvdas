import json
from pathlib import Path
import tempfile
import unittest

import yaml

from contrib.deepsignal.runbooks import runbooks


RUNBOOK = """---
stream: tsg1
endpoint: /dev/ttyUSB0
baud: 9600
format: SBE21
power: science rack PDU 2
spare_location: wet lab cabinet
escalation: Call the marine technician.
owner: A. Tech
causes:
  - check: Check the serial cable.
    fix: Reseat the serial cable.
    stages: [read]
  - check: Check the parser log.
    fix: Restore the format definition.
    stages: [parse]
---
Keep the intake clean. <script>alert('still text')</script>
"""


class RunbookTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.directory = Path(self.tempdir.name)
        (self.directory / "tsg1.md").write_text(RUNBOOK, encoding="utf-8")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_front_matter_parse_and_markdown_stays_text(self):
        loaded = runbooks.load_all(self.directory)
        self.assertEqual(loaded["tsg1"]["baud"], 9600)
        self.assertIn("<script>alert('still text')</script>", loaded["tsg1"]["text"])
        json.dumps(loaded)

    def test_stage_filtering_is_json_safe(self):
        runbooks.load_all(self.directory)
        result = runbooks.for_alarm("tsg1", "parse")
        self.assertEqual(["Check the parser log."],
                         [cause["check"] for cause in result["causes"]])
        json.dumps(result)

    def test_fix_append_and_latest_three(self):
        runbooks.load_all(self.directory)
        for number in range(4):
            runbooks.record_fix("tsg1", f"fix {number}", "operator")
        result = runbooks.for_alarm("tsg1", "read")
        self.assertEqual(["fix 3", "fix 2", "fix 1"],
                         [fix["what"] for fix in result["last_fixes"]])

    def test_draft_from_nbp1406_shape_and_history(self):
        cruise = yaml.safe_load(Path("test/NBP1406/NBP1406_port_defs.yaml").read_text())
        result = runbooks.draft("tsg1", cruise,
                                {"serial": "21-1234", "location": "wet lab"})
        self.assertEqual("/tmp/tty_tsg1", result["endpoint"])
        self.assertEqual(9600, result["baud"])
        self.assertEqual("DRAFT", result["owner"])
        self.assertEqual("21-1234", result["serial"])

    def test_check_findings(self):
        (self.directory / "draft.md").write_text(
            RUNBOOK.replace("stream: tsg1", "stream: draft")
            .replace("owner: A. Tech", "owner: DRAFT\ndrafted: 2020-01-01")
            .replace("check: Check the parser log.", "check: ''"), encoding="utf-8")
        findings = runbooks.check(self.directory, ["tsg1", "draft", "missing"])
        joined = "\n".join(findings)
        self.assertIn("missing: runbook is missing", joined)
        self.assertIn("draft: owner is missing", joined)
        self.assertIn("draft: draft is stale", joined)
        self.assertIn("draft: cause 2 has no check", joined)


if __name__ == "__main__":
    unittest.main()
