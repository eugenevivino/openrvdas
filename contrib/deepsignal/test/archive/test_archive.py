import contextlib
import datetime
import io
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

from contrib.deepsignal.archive import archive


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _old_file(self, name="old.log", data=b"abc\n" * 1000):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (1, 1))
        return path

    def test_round_trip_available_codecs_and_auto_fallback(self):
        codecs = ["xz", "gzip"]
        if shutil.which("zstd"):
            codecs.append("zstd")
        for codec in codecs:
            with self.subTest(codec=codec):
                directory = self.root / codec
                directory.mkdir()
                source = self._old_file(f"{codec}/sample.log")
                result = archive.compress_closed(directory, codec=codec, min_age_s=0)
                self.assertEqual(source.read_bytes(), archive.decompress(result[0].output))
        auto_dir = self.root / "auto"
        auto_dir.mkdir()
        self._old_file("auto/sample.log")
        result = archive.compress_closed(auto_dir, codec="auto", min_age_s=0)
        self.assertEqual("zstd" if shutil.which("zstd") else "xz", result[0].codec)

    def test_today_and_young_files_are_untouched(self):
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        dated = self._old_file(f"sensor-{today}.log")
        young = self.root / "young.log"
        young.write_text("still open", encoding="utf-8")
        self.assertEqual([], archive.compress_closed(self.root, min_age_s=3600))
        self.assertTrue(dated.exists())
        self.assertTrue(young.exists())

    def test_corrupt_output_is_caught_and_original_kept(self):
        source = self._old_file()
        item = archive.compress_closed(self.root, codec="gzip", min_age_s=0)[0]
        item.output.write_bytes(b"corrupt")
        with self.assertRaises(archive.VerificationError):
            archive.verify(self.root)
        self.assertTrue(source.exists())

    def test_delete_requires_flag_and_verified_copy(self):
        source = self._old_file("keep.log")
        archive.compress_closed(self.root, codec="gzip", min_age_s=0)
        self.assertTrue(source.exists())
        source = self._old_file("delete.log")
        archive.compress_closed(self.root, codec="gzip", min_age_s=0,
                                delete_originals=True)
        self.assertFalse(source.exists())

    def test_manifest_is_append_only_and_output_reproducible(self):
        self._old_file()
        first = archive.compress_closed(self.root, codec="gzip", min_age_s=0)[0]
        compressed = first.output.read_bytes()
        manifest = (self.root / "MANIFEST.sha256").read_bytes()
        first.output.unlink()
        archive.compress_closed(self.root, codec="gzip", min_age_s=0)
        self.assertEqual(compressed, first.output.read_bytes())
        self.assertTrue((self.root / "MANIFEST.sha256").read_bytes().startswith(manifest))

    def test_bundle_priority_order_and_budget(self):
        self._old_file("high/a.log", b"A" * 20)
        self._old_file("high/b.log", b"B" * 20)
        self._old_file("low/c.log", b"C" * 20)
        spec = {"cruise": "NBP", "root": str(self.root), "bundles": [
            {"priority": 1, "budget": 25, "globs": ["high/*"]},
            {"priority": 5, "budget": 100, "globs": ["low/*"]}]}
        outputs = archive.bundle(spec, self.root / "shore", codec="xz", now="20200101T000000Z")
        self.assertEqual([1, 5], [item.priority for item in outputs])
        with tarfile.open(fileobj=io.BytesIO(archive.decompress(outputs[0].archive))) as tar:
            names = [member.name for member in tar.getmembers() if member.isfile()]
        self.assertEqual(["high/a.log"], names)

    def test_plan_touches_nothing(self):
        self._old_file()
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            archive.plan(self.root, codec="gzip", min_age_s=0)
        after = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        self.assertEqual(before, after)
        self.assertIn("old.log", output.getvalue())


if __name__ == "__main__":
    unittest.main()
