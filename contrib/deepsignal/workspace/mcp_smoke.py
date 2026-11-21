"""Model-free real-stdio SDK journey; run in the admitted fixture environment."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
import sys

from jsonschema import validate
from mcp import Client, StdioServerParameters

from .service import Workspace

DEPLOYMENT = 'fixture-vessel'
TOOLS = {
    'ds_get_system', 'ds_list_assets', 'ds_get_health', 'ds_query_data',
    'ds_analyze', 'ds_get_configuration', 'ds_create_draft',
    'ds_validate_draft', 'ds_replay_draft', 'ds_create_investigation',
    'ds_add_finding', 'ds_export_investigation', 'ds_get_artifact',
}


async def smoke(state_path: Path) -> dict:
    repository = Path(__file__).resolve().parents[3]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=['-B', '-m', 'contrib.deepsignal.workspace.mcp_server',
              '--state', str(state_path.resolve())],
        env={'PYTHONPATH': str(repository), 'PYTHONUNBUFFERED': '1',
             'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'},
    )
    direct = Workspace(state_path)
    async with asyncio.timeout(45), Client(parameters) as client:
        catalog = await client.list_tools()
        tools = {tool.name: tool for tool in catalog.tools}
        assert set(tools) == TOOLS, 'Unexpected tool catalog'
        assert tools['ds_create_draft'].annotations.read_only_hint is False
        assert tools['ds_get_artifact'].annotations.read_only_hint is True
        for tool in tools.values():
            assert tool.input_schema['properties']['deployment_id']['maxLength'] == 160
            assert tool.output_schema, f'Missing output schema: {tool.name}'

        async def call(method: str, **arguments) -> dict:
            arguments = {'deployment_id': DEPLOYMENT, **arguments}
            result = await client.call_tool(method, arguments)
            assert not result.is_error, (method, result.content)
            envelope = result.structured_content
            validate(envelope, tools[method].output_schema)
            json.dumps(envelope, allow_nan=False)
            assert envelope['status'] in ('success', 'partial'), envelope
            assert envelope['deployment_id'] == DEPLOYMENT
            return envelope['data']

        await call('ds_get_system')
        assets = await call('ds_list_assets')
        assert assets['assets']
        health = await call('ds_get_health')
        assert health['assets']
        dataset = await call('ds_query_data', stream_id='fixture-vessel/temperature',
                             start=0, end=6)
        dataset_id = dataset['dataset_id']
        independent_query = direct.call('ds_query_data', {
            'deployment_id': DEPLOYMENT, 'stream_id': 'fixture-vessel/temperature',
            'start': 0, 'end': 6,
        })
        assert independent_query['data']['dataset_id'] == dataset_id
        analysis = await call('ds_analyze', dataset_id=dataset_id)
        direct_analysis = direct.call('ds_analyze', {
            'deployment_id': DEPLOYMENT, 'dataset_id': dataset_id,
        })['data']
        for field in ('count', 'finite_count', 'missing_count', 'nonfinite_count',
                      'min', 'max', 'mean', 'median', 'stddev', 'unit',
                      'mean_convention', 'stddev_convention'):
            assert analysis[field] == direct_analysis[field], field
        assert analysis['finite_count'] == 4
        assert analysis['mean'] == analysis['median'] == 15
        assert math.isclose(analysis['stddev'], math.sqrt(17), rel_tol=1e-12)

        configuration = await call('ds_get_configuration')
        assert 'TEMP={temperature:g}' in configuration['supported_patterns']
        draft = await call('ds_create_draft',
                           base_snapshot_id=configuration['snapshot_id'],
                           pattern='TEMP={temperature:g}')
        validation = await call('ds_validate_draft', draft_id=draft['draft_id'],
                                revision=draft['revision'])
        assert validation['checks']
        replay_args = {'draft_id': draft['draft_id'], 'revision': draft['revision'],
                       'dataset_id': dataset_id}
        replay = await call('ds_replay_draft', **replay_args)
        direct_replay = direct.call('ds_replay_draft', {
            'deployment_id': DEPLOYMENT, **replay_args,
        })['data']
        for field in ('baseline_count', 'candidate_count', 'expected_count', 'passed'):
            assert replay[field] == direct_replay[field], field
        assert replay['baseline_count'] == 0
        assert replay['candidate_count'] == replay['expected_count'] == 4
        assert replay['passed'] is True, replay

        investigation = await call(
            'ds_create_investigation', title='Simulated parser incident',
            evidence_ids=[dataset_id, analysis['artifact_id'], replay['artifact_id']],
        )
        updated = await call(
            'ds_add_finding', investigation_id=investigation['investigation_id'],
            expected_revision=investigation['revision'], kind='hypothesis',
            text='Fixture mapping explains the replay difference; no vessel claim.',
            evidence_ids=[replay['artifact_id']],
        )
        assert updated['revision'] == investigation['revision'] + 1
        report = await call('ds_export_investigation',
                            investigation_id=investigation['investigation_id'])
        assert report['report'] and report['manifest']
        artifact = await call('ds_get_artifact', artifact_id=report['artifact_id'])
        assert artifact

        denied = await client.call_tool('ds_get_artifact', {
            'deployment_id': 'other-deployment', 'artifact_id': report['artifact_id'],
        })
        assert denied.is_error
        assert 'PERMISSION_DENIED' in ' '.join(
            block.text for block in denied.content if hasattr(block, 'text')
        )
        oversized = await client.call_tool('ds_get_system', {'deployment_id': 'x' * 161})
        assert oversized.is_error
        stale = await client.call_tool('ds_add_finding', {
            'deployment_id': DEPLOYMENT,
            'investigation_id': investigation['investigation_id'],
            'expected_revision': investigation['revision'], 'kind': 'note',
            'text': 'This stale edit must fail', 'evidence_ids': [],
        })
        assert stale.is_error
        assert 'STALE_REVISION' in ' '.join(
            block.text for block in stale.content if hasattr(block, 'text')
        )
        return {'status': 'PASS', 'transport': 'stdio', 'tools': len(tools),
                'dataset_id': dataset_id, 'mean': analysis['mean'],
                'replay_passed': replay['passed'], 'export_artifact_id': report['artifact_id'],
                'checks': ['output schemas', 'direct-service parity', 'fixture replay',
                           'export', 'scope refusal', 'input bounds', 'stale revision'],
                'codex_interactive': 'NOT RUN', 'live_vessel': 'NOT RUN'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(smoke(args.state)), sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
