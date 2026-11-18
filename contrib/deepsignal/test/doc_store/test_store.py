"""Tests for the DeepSignal instrument document store."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest

import yaml

from contrib.deepsignal.doc_store import store


class DocumentStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name)
        self.root = self.base / "store"
        self.source = self.base / "certificate.pdf"
        self.source.write_bytes(b"certificate contents")

    def call(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = store.main(list(arguments))
        return result, output.getvalue()

    def add_certificate(self):
        return self.call(
            "add", str(self.root), str(self.source), "--instrument", "tsg1",
            "--kind", "calibration_certificate", "--cal-id", "CAL-1",
            "--title", "TSG calibration",
        )

    def test_add_list_duplicate_and_preserve_original(self):
        result, output = self.add_certificate()
        self.assertEqual((0, ""), (result, output))
        self.assertEqual(b"certificate contents", self.source.read_bytes())
        copied = self.root / "tsg1" / "certificate.pdf"
        self.assertEqual(b"certificate contents", copied.read_bytes())

        index = yaml.safe_load((self.root / "index.yaml").read_text())
        document = index["documents"][0]
        self.assertEqual("tsg1/certificate.pdf", document["path"])
        self.assertEqual(len(b"certificate contents"), document["bytes"])
        self.assertRegex(document["sha256"], r"^[0-9a-f]{64}$")

        result, output = self.call("list", str(self.root), "--instrument", "tsg1")
        self.assertEqual(0, result)
        self.assertIn("TSG calibration", output)
        self.assertIn("CAL-1", output)

        result, output = self.add_certificate()
        self.assertEqual(1, result)
        self.assertIn("duplicate sha256", output)
        self.assertIn("tsg1/certificate.pdf", output)

    def test_verify_reports_missing_changed_and_stray_files(self):
        self.add_certificate()
        copied = self.root / "tsg1" / "certificate.pdf"
        copied.unlink()
        result, output = self.call("verify", str(self.root))
        self.assertEqual(1, result)
        self.assertIn("missing: tsg1/certificate.pdf", output)

        copied.write_bytes(b"changed")
        stray = self.root / "tsg1" / "notes.txt"
        stray.write_text("unindexed")
        result, output = self.call("verify", str(self.root))
        self.assertEqual(1, result)
        self.assertIn("checksum mismatch: tsg1/certificate.pdf", output)
        self.assertIn("unindexed: tsg1/notes.txt", output)

    def test_crosscheck_reports_both_directions(self):
        self.add_certificate()
        history = self.base / "history.yaml"
        history.write_text(yaml.safe_dump({"instruments": [{
            "id": "tsg1", "serial": "S1", "events": [
                {"type": "calibration", "cal_id": "CAL-2",
                 "certificate": "missing-certificate.pdf"},
            ],
        }]}))
        result, output = self.call("crosscheck", str(self.root), str(history))
        self.assertEqual(1, result)
        self.assertIn("unknown calibration: tsg1 CAL-1", output)
        self.assertIn("missing document: tsg1 CAL-2 missing-certificate.pdf", output)

    def test_path_traversal_in_index_is_refused(self):
        self.root.mkdir()
        (self.root / "index.yaml").write_text(yaml.safe_dump({"documents": [{
            "path": "../secret", "instrument": "tsg1", "kind": "other",
            "title": "bad", "added": "2026-11-18T00:00:00Z",
            "sha256": "0" * 64, "bytes": 0,
        }]}))
        result, output = self.call("verify", str(self.root))
        self.assertEqual(1, result)
        self.assertIn("invalid path", output)


if __name__ == "__main__":
    unittest.main()
