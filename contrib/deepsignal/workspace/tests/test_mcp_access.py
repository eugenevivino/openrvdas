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
                args=['-B', '-m', 'contrib.deepsignal.workspace.mcp_server',
                      '--state', str(Path(directory) / 'state.sqlite3')],
                env={'PYTHONPATH': str(Path(__file__).resolve().parents[4]),
                     'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'},
            )
            async with Client(parameters) as client:
                tools = await client.list_tools()
                allowed = {'ds_get_system', 'ds_list_assets', 'ds_get_health', 'ds_get_artifact'}
                self.assertEqual({tool.name for tool in tools.tools}, allowed)
                self.assertTrue(all(tool.annotations.read_only_hint for tool in tools.tools))
                result = await client.call_tool('ds_get_system', {'deployment_id': 'fixture-vessel'})
                self.assertFalse(result.is_error)
                data = result.structured_content['data']
                self.assertEqual(data['permissions'], ['read'])
                self.assertEqual({key for key in data['capabilities'] if key.startswith('ds_')}, allowed)
                denied = await client.call_tool('ds_create_investigation', {
                    'deployment_id': 'fixture-vessel', 'title': 'unapproved write', 'evidence_ids': [],
                })
                self.assertTrue(denied.is_error)
                promoted = await client.call_tool('ds_get_system', {
                    'deployment_id': 'fixture-vessel', 'access_mode': 'fixture-editor',
                })
                self.assertTrue(promoted.is_error)
                health = await client.call_tool('ds_get_health', {'deployment_id': 'fixture-vessel'})
                self.assertFalse(health.is_error)


if __name__ == '__main__':
    unittest.main()
