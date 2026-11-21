"""The real MCP transport defaults to observation, not fixture editing."""

from pathlib import Path
import sys
import tempfile
import unittest

from mcp import Client, StdioServerParameters


class FixtureMcpAccess(unittest.IsolatedAsyncioTestCase):
    async def test_default_client_only_observes_and_cannot_promote_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-B",
                    "-m",
                    "contrib.deepsignal.workspace.mcp_server",
                    "--state",
                    str(Path(directory) / "state.sqlite3"),
                ],
                env={
                    "PYTHONPATH": str(Path(__file__).resolve().parents[4]),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONNOUSERSITE": "1",
                },
            )
            async with Client(parameters) as client:
                tools = await client.list_tools()
                reads = {"ds_get_system", "ds_list_assets", "ds_get_health", "ds_get_artifact"}
                derived = {"ds_query_data", "ds_analyze", "ds_get_configuration"}
                allowed = reads | derived
                self.assertEqual({tool.name for tool in tools.tools}, allowed)
                self.assertTrue(
                    all(
                        tool.annotations.read_only_hint
                        for tool in tools.tools
                        if tool.name in reads
                    )
                )
                self.assertTrue(
                    all(
                        not tool.annotations.read_only_hint
                        for tool in tools.tools
                        if tool.name in derived
                    )
                )
                result = await client.call_tool(
                    "ds_get_system", {"deployment_id": "fixture-vessel"}
                )
                self.assertFalse(result.is_error)
                data = result.structured_content["data"]
                self.assertEqual(data["permissions"], ["derive", "read"])
                self.assertEqual(
                    {key for key in data["capabilities"] if key.startswith("ds_")}, allowed
                )
                query = await client.call_tool(
                    "ds_query_data",
                    {
                        "deployment_id": "fixture-vessel",
                        "stream_id": "fixture-vessel/temperature",
                        "start": 0,
                        "end": 6,
                    },
                )
                self.assertFalse(query.is_error)
                analysis = await client.call_tool(
                    "ds_analyze",
                    {
                        "deployment_id": "fixture-vessel",
                        "dataset_id": query.structured_content["data"]["dataset_id"],
                    },
                )
                self.assertFalse(analysis.is_error)
                self.assertEqual(analysis.structured_content["data"]["mean"], 15)
                self.assertEqual(
                    analysis.structured_content["data"]["missing_expected_times"], [2, 3]
                )
                configuration = await client.call_tool(
                    "ds_get_configuration", {"deployment_id": "fixture-vessel"}
                )
                self.assertFalse(configuration.is_error)
                denied = await client.call_tool(
                    "ds_create_investigation",
                    {
                        "deployment_id": "fixture-vessel",
                        "title": "unapproved write",
                        "evidence_ids": [],
                    },
                )
                self.assertTrue(denied.is_error)
                draft = await client.call_tool(
                    "ds_create_draft",
                    {
                        "deployment_id": "fixture-vessel",
                        "base_snapshot_id": configuration.structured_content["data"]["snapshot_id"],
                        "pattern": "TEMP={temperature:g}",
                    },
                )
                self.assertTrue(draft.is_error)
                promoted = await client.call_tool(
                    "ds_get_system",
                    {
                        "deployment_id": "fixture-vessel",
                        "access_mode": "fixture-editor",
                    },
                )
                self.assertTrue(promoted.is_error)
                health = await client.call_tool(
                    "ds_get_health", {"deployment_id": "fixture-vessel"}
                )
                self.assertFalse(health.is_error)


if __name__ == "__main__":
    unittest.main()
