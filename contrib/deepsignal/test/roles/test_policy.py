"""Tests for the DeepSignal role policy engine."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from contrib.deepsignal.roles.policy import Policy, PolicyError, explain


EXAMPLE = Path("contrib/deepsignal/configs/roles_example.yaml")


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.policy = Policy.load(EXAMPLE)

    def test_role_ordering_and_every_example_action(self):
        expected = {
            "view.live": "public",
            "view.health": "science",
            "download.binned": "science",
            "download.raw": "tech",
            "corrections.approve": "tech",
            "config.deploy": "admin",
        }
        roles = ("public", "science", "tech", "admin")
        for action, minimum in expected.items():
            minimum_index = roles.index(minimum)
            for index, role in enumerate(roles):
                self.assertEqual(index >= minimum_index,
                                 self.policy.can(role, action),
                                 (role, action))

    def test_unknown_action_fails_closed_and_logs_once(self):
        with self.assertLogs("contrib.deepsignal.roles.policy", level="WARNING") as logs:
            self.assertFalse(self.policy.can("admin", "unknown.action"))
            self.assertFalse(self.policy.can("admin", "unknown.action"))
        self.assertEqual(1, len(logs.output))
        self.assertIn("unknown.action", logs.output[0])

    def test_unknown_role_fails_load_with_plain_message(self):
        path = self._policy_file("actions:\n  view.live: captain\n")
        with self.assertRaisesRegex(
                PolicyError,
                "actions.view.live saw 'captain'; expected one of public, science, tech, admin; "
                "example: public"):
            Policy.load(path)

    def test_default_role_and_user_mapping(self):
        self.assertEqual("tech", self.policy.role_for("alice"))
        self.assertEqual("public", self.policy.role_for("nobody"))

    def test_explain_prints_action_table(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            explain(self.policy)
        lines = output.getvalue().splitlines()
        self.assertEqual("action               public science tech admin", lines[0])
        self.assertIn("config.deploy        -      -       -    yes", lines)
        self.assertIn("view.live            yes    yes     yes  yes", lines)

    def test_check_warns_for_admin_action_open_to_public(self):
        path = self._policy_file("actions:\n  config.deploy: public\n")
        policy = Policy.load(path)
        with self.assertLogs("contrib.deepsignal.roles.policy", level="WARNING") as logs:
            policy.check()
        self.assertIn("admin action open to public", logs.output[0])

    def _policy_file(self, contents):
        handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        self.addCleanup(Path(handle.name).unlink, missing_ok=True)
        with handle:
            handle.write(contents)
        return handle.name


if __name__ == "__main__":
    unittest.main()
