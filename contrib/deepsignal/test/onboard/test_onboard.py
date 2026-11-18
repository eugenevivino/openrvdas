import tempfile
import unittest
from pathlib import Path

import yaml

from contrib.deepsignal.onboard.diff import proposal_diff, write_proposal
from contrib.deepsignal.onboard.fingerprint import identify
from contrib.deepsignal.onboard.propose import propose, proposal_yaml
from contrib.deepsignal.onboard.trial import run_trial
from logger.utils import read_config

DATA = Path(__file__).parent / "data"


class OnboardTest(unittest.TestCase):
    def test_known_captures_are_identified_with_evidence(self):
        cases = (("seapath.txt", "Seapath"), ("knudsen.txt", "Knudsen3260"))
        for filename, expected in cases:
            lines = (DATA / filename).read_text().splitlines()
            candidate = identify(lines)[0]
            self.assertIn(expected, candidate.device_type)
            self.assertGreaterEqual(candidate.score, 0.8)
            self.assertIn("lines parsed as", candidate.evidence)
            self.assertTrue(candidate.fields_seen)

    def test_junk_has_raw_fallback(self):
        candidates = identify(["noise", "1,2", "$BROKEN*00", "garbage"])
        self.assertEqual("No known device matched", candidates[0].device_type)
        self.assertEqual(0, candidates[0].score)

    def test_proposal_loads_and_trial_counts(self):
        capture = DATA / "knudsen.txt"
        candidate = identify(capture.read_text().splitlines())[0]
        proposal = propose(candidate, {"serial": {"port": "/dev/ttyUSB0", "baudrate": 9600}})
        text = proposal_yaml(proposal, capture)
        self.assertIn("proposed by the DeepSignal onboarding wizard", text)
        self.assertIn("onboard-off", proposal["logger_configs"])
        self.assertEqual(proposal, yaml.safe_load(text))
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as output:
            output.write(text)
            output.flush()
            self.assertEqual(proposal, read_config.read_config(output.name))
        result = run_trial(capture, candidate)
        self.assertEqual(12, result.records_parsed)
        self.assertEqual([], result.failed_lines)
        self.assertIn("LFDepth", result.fields)
        self.assertEqual("meters", result.units["LFDepth"])

    def test_diff_only_adds_and_write_refuses_overwrite(self):
        candidate = identify((DATA / "knudsen.txt").read_text().splitlines())[0]
        proposal = propose(candidate, {"udp": {"port": 5000}})
        diff = proposal_diff("test/NBP1406/NBP1406_cruise.yaml", proposal)
        added = [line for line in diff.splitlines()
                 if line.startswith("+") and not line.startswith("+++")]
        removed = [line for line in diff.splitlines()
                   if line.startswith("-") and not line.startswith("---")]
        self.assertTrue(added)
        self.assertFalse(removed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal.yaml"
            write_proposal(path, proposal, DATA / "knudsen.txt")
            message = "write path: saw existing file.*expected a new path"
            with self.assertRaisesRegex(FileExistsError, message):
                write_proposal(path, proposal, DATA / "knudsen.txt")


if __name__ == "__main__":
    unittest.main()
