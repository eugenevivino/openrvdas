import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contrib.deepsignal.workspace.service import Workspace, Principal


class InvestigationJourney(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workspace.sqlite3"
        self.service = Workspace(self.path)
        self.addCleanup(self.tmp.cleanup)

    def call(self, method, **arguments):
        result = self.service.call(method, {"deployment_id": "fixture-vessel", **arguments})
        self.assertNotEqual(result["status"], "error", result)
        json.dumps(result, allow_nan=False)
        return result["data"]

    def test_technician_can_resume_evidence_handoff_without_a_model(self):
        dataset = self.call("ds_query_data", stream_id="fixture-vessel/temperature", start=0, end=6)
        result = self.call("ds_analyze", dataset_id=dataset["dataset_id"])
        self.assertEqual(result["mean"], 15)
        self.assertEqual(result["median"], 15)
        self.assertEqual(result["missing_expected_times"], [2, 3])
        self.assertEqual(result["mean_convention"], "observation-weighted")
        investigation = self.call(
            "ds_create_investigation",
            title="Stale temperature",
            evidence_ids=[dataset["dataset_id"], result["artifact_id"]],
        )
        self.service = Workspace(self.path)
        report = self.call(
            "ds_export_investigation", investigation_id=investigation["investigation_id"]
        )
        self.assertIn("Stale temperature", report["report"])
        self.assertIn(result["artifact_id"], report["report"])
        self.assertIn("SIMULATED", report["report"])

    def test_configuration_correction_produces_exact_records_not_just_more_rows(self):
        dataset = self.call("ds_query_data", stream_id="fixture-vessel/temperature", start=0, end=6)
        configuration = self.call("ds_get_configuration")
        draft = self.call(
            "ds_create_draft",
            base_snapshot_id=configuration["snapshot_id"],
            pattern="TEMP={temperature:g}",
        )
        validation = self.call("ds_validate_draft", draft_id=draft["draft_id"], revision=1)
        self.assertEqual(validation["checks"][-1]["status"], "not-run")
        replay = self.call(
            "ds_replay_draft",
            draft_id=draft["draft_id"],
            revision=1,
            dataset_id=dataset["dataset_id"],
        )
        self.assertEqual(replay["baseline_count"], 0)
        self.assertEqual(replay["candidate_count"], 4)
        self.assertTrue(replay["passed"])
        self.assertEqual(
            [(r["timestamp"], r["fields"]["temperature"]) for r in replay["candidate"]],
            [(0, 10), (1, 12), (4, 18), (5, 20)],
        )
        unchanged = self.call(
            "ds_create_draft",
            base_snapshot_id=configuration["snapshot_id"],
            pattern="T={temperature:g}",
        )
        no_change = self.call(
            "ds_replay_draft",
            draft_id=unchanged["draft_id"],
            revision=1,
            dataset_id=dataset["dataset_id"],
        )
        self.assertFalse(no_change["passed"])
        self.assertEqual(
            self.call("ds_get_configuration")["snapshot_id"], configuration["snapshot_id"]
        )

    def test_independent_integer_and_float_queries_share_one_dataset_identity(self):
        first = self.call("ds_query_data", stream_id="fixture-vessel/temperature", start=0, end=6)
        second = self.call(
            "ds_query_data", stream_id="fixture-vessel/temperature", start=0.0, end=6.0
        )
        self.assertEqual(first["dataset_id"], second["dataset_id"])

    def test_empty_and_one_point_selections_do_not_invent_measurements(self):
        empty = self.call("ds_query_data", stream_id="fixture-vessel/temperature", start=2, end=4)
        result = self.call("ds_analyze", dataset_id=empty["dataset_id"])
        self.assertEqual(result["finite_count"], 0)
        self.assertIsNone(result["mean"])
        self.assertEqual(result["missing_expected_times"], [2, 3])
        one = self.call("ds_query_data", stream_id="fixture-vessel/temperature", start=0, end=1)
        result = self.call("ds_analyze", dataset_id=one["dataset_id"])
        self.assertEqual(result["mean"], 10)
        self.assertEqual(result["stddev"], 0)

    def test_permissions_are_server_owned_and_artifact_reads_are_rechecked(self):
        dataset = self.call("ds_query_data", stream_id="fixture-vessel/temperature", start=0, end=6)
        read_only = Workspace(self.path, Principal(permissions=frozenset({"read"})))
        result = read_only.call(
            "ds_create_investigation",
            {"deployment_id": "fixture-vessel", "title": "must not save", "evidence_ids": []},
        )
        self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
        other = Workspace(self.path, Principal(deployment_id="another-vessel"))
        result = other.call(
            "ds_get_artifact",
            {"deployment_id": "fixture-vessel", "artifact_id": dataset["dataset_id"]},
        )
        self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
        result = self.service.call(
            "ds_get_system", {"deployment_id": "fixture-vessel", "role": "admin"}
        )
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_changed_runtime_identity_cannot_keep_validation_green(self):
        original = Path.read_text

        def changed(path, *args, **kwargs):
            content = original(path, *args, **kwargs)
            if path.name == "compatibility.json":
                value = json.loads(content)
                value["source_sha256"]["logger/transforms/parse_transform.py"] = "0" * 64
                return json.dumps(value)
            return content

        config = self.call("ds_get_configuration")
        draft = self.call(
            "ds_create_draft",
            base_snapshot_id=config["snapshot_id"],
            pattern="TEMP={temperature:g}",
        )
        with patch.object(Path, "read_text", changed):
            result = self.service.call(
                "ds_validate_draft",
                {"deployment_id": "fixture-vessel", "draft_id": draft["draft_id"], "revision": 1},
            )
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["error"]["code"], "STALE_REVISION")

    def test_every_accepted_note_keeps_investigation_exportable(self):
        item = self.call("ds_create_investigation", title="Bounded notes", evidence_ids=[])
        accepted = 0
        for _ in range(32):
            result = self.service.call(
                "ds_add_finding",
                {
                    "deployment_id": "fixture-vessel",
                    "investigation_id": item["investigation_id"],
                    "expected_revision": item["revision"],
                    "kind": "note",
                    "text": "x" * 4000,
                    "evidence_ids": [],
                },
            )
            if result["status"] == "error":
                self.assertEqual(result["error"]["code"], "LIMIT_EXCEEDED")
                break
            item = result["data"]
            accepted += 1
            self.call("ds_export_investigation", investigation_id=item["investigation_id"])
        self.assertGreater(accepted, 0)


if __name__ == "__main__":
    unittest.main()
