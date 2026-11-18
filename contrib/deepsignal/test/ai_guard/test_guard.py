import os
import tempfile
import unittest

from contrib.deepsignal.ai_guard import audit, budget, secrets


class GuardTest(unittest.TestCase):
    def test_budget_units_and_settle(self):
        with tempfile.TemporaryDirectory() as root:
            meter = budget.BudgetMeter(os.path.join(root, "budget.json"),
                                       {"day": {"usd": 2, "tokens": 10,
                                                "bytes": 20}})
            reservation = meter.check_and_reserve(1, "usd", "ship")
            self.assertTrue(reservation)
            meter.settle(reservation, .5)
            self.assertTrue(meter.check_and_reserve(1.5, "usd", "ship"))
            self.assertFalse(meter.check_and_reserve(.01, "usd", "ship"))
            self.assertTrue(meter.check_and_reserve(10, "tokens", "ship"))
            self.assertTrue(meter.check_and_reserve(20, "bytes", "ship"))

    def test_audit_chain_tamper_and_hmac(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "audit.jsonl")
            log = audit.AuditLog(path, sign_key=b"right")
            log.append({"event": 1})
            log.append({"event": 2})
            self.assertTrue(audit.verify(path, b"right")["ok"])
            self.assertFalse(audit.verify(path, b"wrong")["ok"])
            with open(path, encoding="utf-8") as source:
                lines = source.readlines()
            lines[0] = lines[0].replace('"event":1', '"event":9')
            with open(path, "w", encoding="utf-8") as target:
                target.writelines(lines)
            result = audit.verify(path, b"right")
            self.assertFalse(result["ok"])
            self.assertEqual(1, result["first_break"])

    def test_token_hash(self):
        stored = secrets.hash_token("not-plaintext")
        self.assertNotIn("not-plaintext", stored)
        self.assertTrue(secrets.check_token("not-plaintext", stored))
        self.assertFalse(secrets.check_token("wrong", stored))


if __name__ == "__main__":
    unittest.main()
