"""Acceptance failures must remain failures even when Python is optimized."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contrib.deepsignal.workspace import mcp_smoke


class McpAcceptanceChecks(unittest.TestCase):
    def test_actual_stdio_catalog_mismatch_cannot_be_reported_as_pass(self):
        expected_catalogs = (
            mcp_smoke.TOOLS | {'required_tool_not_registered'},
            mcp_smoke.TOOLS - {'ds_get_system'},
        )
        for expected in expected_catalogs:
            with self.subTest(expected=sorted(expected)):
                with tempfile.TemporaryDirectory() as directory:
                    with patch.object(mcp_smoke, 'TOOLS', expected):
                        with self.assertRaises(Exception) as failure:
                            asyncio.run(mcp_smoke.smoke(Path(directory) / 'state.sqlite3'))
                        # SDK task groups may wrap the original acceptance failure.
                        pending = [failure.exception]
                        leaves = []
                        while pending:
                            error = pending.pop()
                            if isinstance(error, BaseExceptionGroup):
                                pending.extend(error.exceptions)
                            else:
                                leaves.append((type(error), str(error)))
                        self.assertEqual(leaves, [(AssertionError, 'Unexpected tool catalog')])


if __name__ == '__main__':
    unittest.main()
