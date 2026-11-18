import json
import os
import tempfile
import unittest

from contrib.deepsignal.ai_triage import context, models, redact, schema, setup
from contrib.deepsignal.ai_triage.service import TriageService
from contrib.deepsignal.ai_triage.triggers import TriggerManager


class FakeClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def post(self, url, headers, body, timeout, proxy=None):
        self.calls.append((url, headers, body, timeout, proxy))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeVault:
    def __init__(self, protector):
        self.kind = protector
        self.values = {}

    def put(self, namespace, name, value):
        self.values[(namespace, name)] = value

    def get(self, namespace, name):
        return self.values[(namespace, name)]

    def protector(self):
        return self.kind


GOOD = {"summary": "Stage failed. Check it.", "causes": [
    {"cause": "cable", "likelihood": "high", "evidence": ["r1"]}],
    "checks": [{"step": "inspect", "kind": "look", "runbook_ref": "r1"}],
    "cannot_tell": False, "confidence": .8}


class TriageTest(unittest.TestCase):
    def test_triggers_and_cache(self):
        trigger = TriggerManager(hold_s=60, digest_times=["0400"])
        self.assertFalse(trigger.transition("s", "DEGRADED", 0))
        self.assertFalse(trigger.transition("s", "DEGRADED", 59))
        self.assertTrue(trigger.transition("s", "DEGRADED", 60))
        self.assertTrue(trigger.alert("s", "A1"))
        self.assertFalse(trigger.alert("s", "A3"))
        self.assertTrue(trigger.request("s"))
        self.assertTrue(trigger.digest("0400", "2026-01-01"))
        self.assertFalse(trigger.digest("0400", "2026-01-01"))

    def test_context_limit_and_redaction(self):
        snapshot = {"chain": "x" * 500, "token": "fake-token-123",
                    "email": "tech@example.com", "refs": [{"id": "r1"}]}
        pack, counts = context.build_pack(snapshot, max_context_tokens=30)
        encoded = json.dumps(pack)
        self.assertLessEqual(len(encoded), 120)
        self.assertNotIn("fake-token-123", encoded)
        self.assertGreater(counts["credentials"], 0)

    def test_schema_refs_and_write_proposal(self):
        value = dict(GOOD)
        value["causes"] += [{"cause": "guess", "likelihood": "low",
                             "evidence": ["invented"]}]
        value["checks"] += [{"step": "restart", "kind": "write_action",
                             "runbook_ref": "r1"}]
        valid = schema.validate(value, {"r1"})
        self.assertEqual(1, len(valid["causes"]))
        self.assertEqual("proposal", valid["checks"][1]["kind"])
        self.assertTrue(valid["checks"][1]["needs_approval"])

    def test_models_shapes_and_host_guard(self):
        vault = FakeVault("tpm2")
        vault.put("ai-triage", "openai", "secret")
        client = FakeClient([{"choices": [{"message": {"content": "{}"}}],
                              "usage": {}}])
        model = models.ApiModel("openai", "https://api.example/v1/chat/completions",
                                "m", "openai", client, ["api.example"],
                                vault=vault)
        model.complete({"a": 1})
        body = json.loads(client.calls[0][2])
        self.assertIn("messages", body)
        anth = FakeClient([{"content": [{"text": "{}"}], "usage": {}}])
        models.ApiModel("anthropic", "https://anth.example/v1/messages", "m",
                        "openai", anth, ["anth.example"], vault=vault).complete({})
        self.assertIn("max_tokens", json.loads(anth.calls[0][2]))
        refused = FakeClient([])
        bad = models.ApiModel("openai", "https://bad.example/v1/chat/completions",
                              "m", "openai", refused, ["good.example"], vault=vault)
        with self.assertRaises(models.HostNotAllowed):
            bad.complete({})
        self.assertFalse(refused.calls)

    def test_redaction_rules(self):
        data = {"password": "secret", "note": "a@b.com +1 555-123-4567",
                "held": "x", "eez_secret": "y", "latitude": 12.34567,
                "longitude": -45.67891}
        clean, counts = redact.redact(data, held_fields={"held"},
                                      eez_inside=True,
                                      eez_held_fields={"eez_secret"})
        self.assertNotIn("secret", json.dumps(clean))
        self.assertNotIn("@", json.dumps(clean))
        self.assertEqual(12.35, clean["latitude"])
        self.assertGreater(sum(counts.values()), 3)

    def test_service_retry_fallback_offline_queue_cache_and_local(self):
        with tempfile.TemporaryDirectory() as root:
            vault = FakeVault("hostkey")
            vault.put("ai-triage", "openai", "secret")
            bad = FakeClient([{"choices": [{"message": {"content": "bad"}}]},
                              {"choices": [{"message": {"content": "bad"}}]}])
            api = models.ApiModel("openai", "https://api.example/v1/chat/completions",
                                  "m", "openai", bad, ["api.example"], vault=vault)
            service = TriageService(root, api_model=api, api_enabled=True)
            snapshot = {"stream": "s", "failing_stage": "reader",
                        "runbook_causes": ["power", "cable"],
                        "refs": [{"id": "r1", "text": "reader failed"}]}
            answer = service.briefing("s", snapshot)
            self.assertEqual("no AI used", answer["label"])
            self.assertEqual(2, len(bad.calls))
            service.link_up = False
            pending = service.briefing("new", dict(snapshot, stream="new"))
            self.assertEqual("AI pending", pending["label"])
            self.assertTrue(os.path.exists(os.path.join(root, "queue.jsonl")))
            for n in range(55):
                service._enqueue({"stream": str(n)})
            with open(os.path.join(root, "queue.jsonl")) as queue:
                self.assertEqual(50, len(queue.readlines()))
            local_client = FakeClient([{"choices": [{"message": {
                "content": json.dumps(GOOD)}}], "usage": {}}])
            service.local_model = models.LocalModel("http://localhost:8000/v1/chat/completions",
                                                    "local", local_client)
            service.local_enabled = True
            local = service.briefing("local", dict(snapshot, stream="local"))
            self.assertEqual("local model", local["label"])

    def test_api_disabled_timeline_outcome_learning_and_setup(self):
        with tempfile.TemporaryDirectory() as root:
            service = TriageService(root, api_model=None, api_enabled=False)
            snapshot = {"stream": "s", "failing_stage": "reader",
                        "runbook_causes": ["power"], "refs": [{"id": "r1"}]}
            brief = service.briefing("s", snapshot)
            self.assertEqual("no AI used", brief["label"])
            service.record_outcome(brief["briefing_id"], 0, "power cycled", "tech")
            diff = service.propose_runbook_updates()
            self.assertIn("+ power cycled", diff)
            with open(os.path.join(root, "timeline.jsonl")) as timeline_file:
                timeline = timeline_file.read()
            self.assertIn("ai_briefing", timeline)
            self.assertEqual(2, len(setup.providers()))
            preview = setup.preview(snapshot, 100)
            self.assertIn("removals", preview)

    def test_vault_round_trip_and_missing_vault_disables_ai(self):
        for kind in ("tpm2", "hostkey"):
            vault = FakeVault(kind)
            result = setup.store_key("openai", "ship-secret", vault=vault)
            self.assertEqual("ship-secret", setup.load_key("openai", vault=vault))
            self.assertIn(kind, result["message"])
        client = FakeClient([])
        model = models.ApiModel(
            "openai", "https://api.example/v1/chat/completions", "m",
            "openai", client, ["api.example"], vault_loader=lambda: None)
        with tempfile.TemporaryDirectory() as root:
            answer = TriageService(root, api_model=model, api_enabled=True).briefing(
                "s", {"failing_stage": "reader", "runbook_causes": ["power"]})
        self.assertEqual(setup.VAULT_REQUIRED, answer["message"])
        self.assertFalse(client.calls)


if __name__ == "__main__":
    unittest.main()
