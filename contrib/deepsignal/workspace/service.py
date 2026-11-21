"""Bounded synthetic evidence services shared by UI, CLI and MCP.

No caller supplies paths, endpoints, identities, components or execution authority.
The local OS-user fixture boundary is not production multiuser authorization.
"""
from __future__ import annotations
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import difflib
import inspect
import importlib.metadata
import json
import math
from pathlib import Path
import sqlite3
import statistics
import uuid

DEPLOYMENT = 'fixture-vessel'
LIMITS = {'request_bytes': 65536, 'artifact_bytes': 262144,
          'artifacts': 512, 'database_bytes': 16777216, 'rows': 1000,
          'retention': 'local until operator deletes workspace; no automatic eviction'}
MESSAGES = {
    'INVALID_ARGUMENT': 'Arguments do not match the supported fixture contract.',
    'PERMISSION_DENIED': 'Deployment, action or evidence is not accessible.',
    'LIMIT_EXCEEDED': 'The request or workspace exceeds its limits.',
    'SOURCE_UNAVAILABLE': 'Requested evidence is unavailable.',
    'STALE_REVISION': 'Refresh the revision before editing.',
    'UNSUPPORTED_CAPABILITY': 'This profile does not support that capability.',
    'INSUFFICIENT_COVERAGE': 'The selected evidence cannot answer this request.',
}


class Fault(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identity(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def text(value, maximum=160):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Fault('INVALID_ARGUMENT')
    return value


@dataclass(frozen=True)
class Principal:
    # Set by the process owner, never by a tool argument.
    name: str = 'local-fixture-operator'
    deployment_id: str = DEPLOYMENT
    permissions: frozenset = frozenset({'read', 'write', 'export'})


class Workspace:
    METHODS = {
        'ds_query_data': 'write', 'ds_analyze': 'write',
        'ds_create_investigation': 'write', 'ds_export_investigation': 'export',
        'ds_get_artifact': 'read',
        'ds_get_configuration': 'write', 'ds_create_draft': 'write',
        'ds_validate_draft': 'write', 'ds_replay_draft': 'write',
        'ds_get_system': 'read', 'ds_list_assets': 'read', 'ds_get_health': 'read',
        'ds_add_finding': 'write',
    }

    def __init__(self, state_path: Path, principal: Principal | None = None):
        self.path = Path(state_path)
        self.principal = principal or Principal()
        self.fixture = json.loads((Path(__file__).parent / 'fixtures/incident.json').read_text())
        self.fixture_hash = identity(self.fixture)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS investigations (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY, at TEXT, principal TEXT,
                    method TEXT, result_id TEXT, outcome TEXT);
            ''')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.execute('PRAGMA max_page_count=4096')
        return db

    def call(self, method: str, arguments: dict):
        result_id = uuid.uuid4().hex
        result = {'schema_version': 1, 'result_id': result_id,
                  'deployment_id': DEPLOYMENT, 'as_of': self.fixture['as_of'],
                  'status': 'success', 'data': {}, 'warnings': self.fixture['limitations'],
                  'limits': dict(LIMITS), 'provenance': [self.fixture_hash]}
        try:
            if not isinstance(arguments, dict) or not isinstance(method, str):
                raise Fault('INVALID_ARGUMENT')
            if len(encode(arguments).encode()) > LIMITS['request_bytes']:
                raise Fault('LIMIT_EXCEEDED')
            if (arguments.get('deployment_id') != DEPLOYMENT or
                    self.principal.deployment_id != DEPLOYMENT):
                raise Fault('PERMISSION_DENIED')
            if method not in self.METHODS:
                raise Fault('UNSUPPORTED_CAPABILITY')
            if ('read' not in self.principal.permissions or
                    self.METHODS[method] not in self.principal.permissions):
                raise Fault('PERMISSION_DENIED')
            handler = getattr(self, method)
            inspect.signature(handler).bind(**arguments)
            with closing(self._connect()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                result['data'] = handler(db=db, **arguments)
                if len(encode(result).encode()) > LIMITS['artifact_bytes']:
                    raise Fault('LIMIT_EXCEEDED')
                db.execute('INSERT INTO audit(at,principal,method,result_id,outcome) VALUES (?,?,?,?,?)',
                           (datetime.now(timezone.utc).isoformat(), self.principal.name,
                            method, result_id, 'success'))
        except Fault as exc:
            result.update(status='error', data={}, error={'code': exc.code, 'message': str(exc)})
        except (TypeError, ValueError, RecursionError, OverflowError):
            result.update(status='error', data={}, error={'code': 'INVALID_ARGUMENT',
                          'message': MESSAGES['INVALID_ARGUMENT']})
        except (sqlite3.Error, OSError, ImportError):
            result.update(status='error', data={}, error={'code': 'SOURCE_UNAVAILABLE',
                          'message': MESSAGES['SOURCE_UNAVAILABLE']})
        return result

    def _put(self, db, kind, data):
        body = encode({'deployment_id': DEPLOYMENT, 'kind': kind, 'data': data})
        if len(body.encode()) > LIMITS['artifact_bytes']:
            raise Fault('LIMIT_EXCEEDED')
        key = kind + '-' + hashlib.sha256(body.encode()).hexdigest()
        if not db.execute('SELECT 1 FROM artifacts WHERE id=?', (key,)).fetchone():
            if db.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0] >= LIMITS['artifacts']:
                raise Fault('LIMIT_EXCEEDED')
            db.execute('INSERT INTO artifacts VALUES (?,?)', (key, body))
        return key

    def _get(self, db, key, kind=None):
        text(key)
        row = db.execute('SELECT body FROM artifacts WHERE id=?', (key,)).fetchone()
        if row is None:
            raise Fault('SOURCE_UNAVAILABLE')
        document = json.loads(row[0])
        if document['deployment_id'] != self.principal.deployment_id:
            raise Fault('PERMISSION_DENIED')
        if key != document['kind'] + '-' + hashlib.sha256(row[0].encode()).hexdigest():
            raise Fault('SOURCE_UNAVAILABLE')
        if kind and document['kind'] != kind:
            raise Fault('INVALID_ARGUMENT')
        return document['data']

    def _evidence(self, db, evidence_ids):
        if not isinstance(evidence_ids, list) or len(evidence_ids) > 32:
            raise Fault('INVALID_ARGUMENT')
        for key in evidence_ids:
            self._get(db, key)
        return list(dict.fromkeys(evidence_ids))

    def ds_get_artifact(self, deployment_id, artifact_id, *, db=None):
        return {'artifact_id': artifact_id, 'content': self._get(db, artifact_id)}

    def ds_get_system(self, deployment_id, *, db=None):
        return {'deployment_id': DEPLOYMENT, 'environment': 'SIMULATED',
                'profile': 'fixture-parse-transform-v1', 'version': '0.1.0',
                'source_status': 'fixed synthetic experiment; no vessel connection',
                'permissions': sorted(self.principal.permissions), 'limits': dict(LIMITS),
                'capabilities': {**{key: 'fixture only' for key, permission in self.METHODS.items()
                                   if 'read' in self.principal.permissions and permission in self.principal.permissions},
                                 'live_control': 'unavailable', 'real_archive': 'unverified',
                                 'grafana': 'required; not implemented',
                                 'general_replay': 'unsupported',
                                 'approval_boundary': 'advisory local OS-user boundary'},
                'time_basis': self.fixture['time_basis']}

    def ds_list_assets(self, deployment_id, *, db=None):
        return {'assets': [
            {'id': self.fixture['stream_id'], 'name': 'Temperature parser incident',
             'kind': 'stream', 'unit': self.fixture['unit']},
            {'id': DEPLOYMENT + '/conductivity', 'name': 'Conductivity reference',
             'kind': 'logger', 'unit': 'mS/cm'},
            {'id': DEPLOYMENT + '/auxiliary', 'name': 'Auxiliary logger',
             'kind': 'logger', 'unit': None}],
            'limitations': ['History queries implemented only for temperature reference.']}

    def ds_get_health(self, deployment_id, *, db=None):
        return {'assets': [
            {'id': self.fixture['stream_id'], 'name': 'Temperature parser incident',
             'activity': 'expected active; raw fixture records continue', 'freshness': 'STALE',
             'parsing': 'baseline mapping fails fixture records', 'archive': 'synthetic raw records available; production unverified',
             'age_s': 7, 'last_value': 9, 'unit': self.fixture['unit'],
             'evidence': {'last_parsed_time': -1, 'as_of': 6, 'stale_threshold_s': 2,
                          'rule': 'fixture-freshness-v1', 'quality': 'not evaluated',
                          'source_revision': self.fixture_hash}},
            {'id': DEPLOYMENT + '/conductivity', 'name': 'Conductivity reference',
             'activity': 'expected active', 'freshness': 'CURRENT', 'parsing': 'fixture success',
             'archive': 'unverified', 'age_s': 1, 'last_value': 42, 'unit': 'mS/cm',
             'evidence': {'as_of': 6, 'source': 'explicit simulated state; no scientific validity claim'}},
            {'id': DEPLOYMENT + '/auxiliary', 'name': 'Auxiliary logger',
             'activity': 'intentionally inactive in fixture mode', 'freshness': 'NOT_APPLICABLE',
             'parsing': 'not expected', 'archive': 'not expected', 'age_s': None,
             'last_value': None, 'unit': None, 'evidence': {'mode': 'fixture-underway'}}]}

    def ds_query_data(self, deployment_id, stream_id, start, end, *, db=None):
        if stream_id != self.fixture['stream_id']:
            raise Fault('UNSUPPORTED_CAPABILITY')
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= 6):
            raise Fault('INVALID_ARGUMENT')
        start, end = float(start), float(end)
        data = {key: self.fixture[key] for key in
                ('stream_id', 'unit', 'quantity_kind', 'cadence_s', 'time_basis', 'source_class')}
        data.update(start=start, end=end, source_revision=self.fixture_hash,
                    rows=[r for r in self.fixture['rows'] if start <= r['time'] < end],
                    coverage={'requested': [start, end], 'available': [0, 6],
                              'completeness': 'known for synthetic fixture only',
                              'missing_grid_points_are_not_missing_values': True})
        return {**data, 'dataset_id': self._put(db, 'dataset', data)}

    def ds_analyze(self, deployment_id, dataset_id, *, db=None):
        dataset = self._get(db, dataset_id, 'dataset')
        if dataset['quantity_kind'] != 'scalar':
            raise Fault('UNSUPPORTED_CAPABILITY')
        rows = dataset['rows']
        values = [r['value'] for r in rows if isinstance(r['value'], (int, float))
                  and not isinstance(r['value'], bool) and math.isfinite(r['value'])]
        observed = {r['time'] for r in rows}
        grid = range(math.ceil(dataset['start']), math.ceil(dataset['end']))
        data = {'dataset_id': dataset_id, 'method': 'scalar-summary-v1',
                'unit': dataset['unit'], 'count': len(rows), 'finite_count': len(values),
                'missing_count': sum(r['value'] is None and r.get('reason') != 'nonfinite' for r in rows),
                'nonfinite_count': sum(r.get('reason') == 'nonfinite' for r in rows),
                'min': min(values) if values else None, 'max': max(values) if values else None,
                'mean': statistics.fmean(values) if values else None,
                'median': statistics.median(values) if values else None,
                'stddev': statistics.pstdev(values) if values else None,
                'mean_convention': 'observation-weighted', 'stddev_convention': 'population',
                'missing_expected_times': [t for t in grid if t not in observed],
                'cadence_policy': 'fixture 1 Hz grid anchored at 0; interval end exclusive',
                'exclusions': 'missing/nonfinite values excluded; original rows retained',
                'limitations': ['No physical validity, drift or calibration conclusion.']}
        return {**data, 'artifact_id': self._put(db, 'analysis', data)}

    def ds_create_investigation(self, deployment_id, title, evidence_ids, *, db=None):
        text(title, 200)
        evidence = self._evidence(db, evidence_ids)
        if db.execute('SELECT COUNT(*) FROM investigations').fetchone()[0] >= 128:
            raise Fault('LIMIT_EXCEEDED')
        key = 'investigation-' + uuid.uuid4().hex
        body = {'title': title, 'deployment_id': deployment_id, 'environment': 'SIMULATED',
                'evidence_ids': evidence, 'findings': [], 'author': self.principal.name}
        self._render_export(db, body, 1, key)
        db.execute('INSERT INTO investigations VALUES (?,1,?)', (key, encode(body)))
        return {'investigation_id': key, 'revision': 1}

    def _configuration(self, pattern):
        # Supported component fragment, not an entire cruise definition.
        return {'class': 'ParseTransform', 'kwargs': {
            'record_format': '{data_id:w} {timestamp:g} {field_string}',
            'field_patterns': [pattern], 'quiet': True,
            'metadata': {'temperature': {'units': self.fixture['unit']}}}}

    def ds_get_configuration(self, deployment_id, *, db=None):
        data = {'source': self._configuration(self.fixture['baseline_pattern']),
                'source_revision': self.fixture_hash,
                'component_versions': self._runtime(),
                'loaded_state': 'unknown', 'runtime_state': 'simulated',
                'supported_patterns': self.fixture['supported_patterns'],
                'scope': 'single component fragment, no manager or cruise configuration',
                'affected_assets': [self.fixture['stream_id']]}
        return {**data, 'snapshot_id': self._put(db, 'configuration', data)}

    def ds_create_draft(self, deployment_id, base_snapshot_id, pattern, *, db=None):
        base = self._get(db, base_snapshot_id, 'configuration')
        if not isinstance(pattern, str) or pattern not in self.fixture['supported_patterns']:
            raise Fault('UNSUPPORTED_CAPABILITY')
        source = self._configuration(pattern)
        before = json.dumps(base['source'], indent=2).splitlines(keepends=True)
        after = json.dumps(source, indent=2).splitlines(keepends=True)
        data = {'base_snapshot_id': base_snapshot_id, 'revision': 1, 'source': source,
                'source_diff': ''.join(difflib.unified_diff(before, after, fromfile='baseline', tofile='draft')),
                'behavioral_diff': {'field_patterns': {'before': base['source']['kwargs']['field_patterns'],
                                                     'after': [pattern]},
                                    'affected_assets': base['affected_assets'],
                                    'production_restart_effect': 'unknown; no live proposal'},
                'source_revision': base['source_revision']}
        return {**data, 'draft_id': self._put(db, 'draft', data)}

    def _draft(self, db, draft_id, revision):
        draft = self._get(db, draft_id, 'draft')
        if type(revision) is not int or revision != draft['revision']:
            raise Fault('STALE_REVISION')
        return draft

    def ds_validate_draft(self, deployment_id, draft_id, revision, *, db=None):
        draft = self._draft(db, draft_id, revision)
        base = self._get(db, draft['base_snapshot_id'], 'configuration')
        if self._runtime() != base['component_versions']:
            raise Fault('STALE_REVISION')
        # Static validation never imports/instantiates a component.
        pattern = draft['source']['kwargs']['field_patterns'][0]
        supported = draft['source'] == self._configuration(pattern) and pattern in self.fixture['supported_patterns']
        checks = [{'level': 'L1', 'status': 'passed', 'message': 'Bounded service-generated JSON component fragment.'},
                  {'level': 'L2', 'status': 'passed' if supported else 'failed',
                   'message': 'Exact allowlisted ParseTransform contract; no arbitrary component imports.'},
                  {'level': 'L3', 'status': 'passed', 'message': 'Pinned fixture dependencies; cruise expansion unsupported.'},
                  {'level': 'L4', 'status': 'unsupported', 'message': 'Live destination/mode/restart effects unknown.'},
                  {'level': 'L5', 'status': 'not-run', 'message': 'Run bounded fixture replay separately.'},
                  {'level': 'L6', 'status': 'not-run', 'message': 'Site qualification is separate.'}]
        data = {'draft_id': draft_id, 'revision': revision, 'checks': checks}
        return {**data, 'artifact_id': self._put(db, 'validation', data)}

    def ds_replay_draft(self, deployment_id, draft_id, revision, dataset_id, *, db=None):
        draft = self._draft(db, draft_id, revision)
        dataset = self._get(db, dataset_id, 'dataset')
        if dataset['source_revision'] != draft['source_revision'] or dataset['source_revision'] != self.fixture_hash:
            raise Fault('STALE_REVISION')
        if not dataset['rows']:
            raise Fault('INSUFFICIENT_COVERAGE')
        # Two source-controlled patterns and four bounded synthetic records only.
        pattern = draft['source']['kwargs']['field_patterns'][0]
        if pattern not in self.fixture['supported_patterns'] or draft['source'] != self._configuration(pattern):
            raise Fault('UNSUPPORTED_CAPABILITY')
        baseline = self._get(db, draft['base_snapshot_id'], 'configuration')
        if self._runtime() != baseline['component_versions']:
            raise Fault('STALE_REVISION')
        from logger.transforms.parse_transform import ParseTransform
        def run(source):
            parser = ParseTransform(**source['kwargs'])
            return [value for row in dataset['rows']
                    if (value := parser.transform(row['raw'])) is not None]
        original = run(baseline['source'])
        candidate = run(draft['source'])
        expected = [{'data_id': 'SIM', 'timestamp': row['time'],
                     'fields': {'temperature': row['value']}} for row in dataset['rows']]
        data = {'draft_id': draft_id, 'revision': revision, 'dataset_id': dataset_id,
                'baseline_count': len(original), 'candidate_count': len(candidate),
                'expected_count': len(expected), 'baseline': original, 'candidate': candidate,
                'passed': candidate == expected, 'expected': expected,
                'unit': dataset['unit'], 'unit_source': 'explicit fixture metadata, not inferred',
                'runtime': baseline['component_versions'],
                'limitations': ['Fixed ParseTransform experiment only; no general replay sandbox.',
                                'No devices, manager, destinations, timing or vessel qualification.']}
        return {**data, 'artifact_id': self._put(db, 'replay', data)}

    def _runtime(self):
        manifest = json.loads((Path(__file__).parent / 'compatibility.json').read_text())
        root = Path(__file__).resolve().parents[3]
        actual = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                  for name in manifest['source_sha256']}
        versions = {name: importlib.metadata.version(name)
                    for name in manifest['runtime_dependencies']}
        if actual != manifest['source_sha256'] or versions != manifest['runtime_dependencies']:
            raise Fault('STALE_REVISION')
        return {'source_sha256': actual, 'dependencies': versions}

    def ds_export_investigation(self, deployment_id, investigation_id, *, db=None):
        text(investigation_id)
        row = db.execute('SELECT revision,body FROM investigations WHERE id=?', (investigation_id,)).fetchone()
        if row is None:
            raise Fault('SOURCE_UNAVAILABLE')
        body = json.loads(row[1])
        if body['deployment_id'] != self.principal.deployment_id:
            raise Fault('PERMISSION_DENIED')
        data = self._render_export(db, body, row[0], investigation_id)
        return {**data, 'artifact_id': self._put(db, 'export', data)}

    def _render_export(self, db, body, revision, investigation_id):
        evidence = {key: self._get(db, key) for key in body['evidence_ids']}
        manifest = {**body, 'revision': revision, 'investigation_id': investigation_id,
                    'evidence': evidence, 'limitations': self.fixture['limitations']}
        report = '# SIMULATED watch handoff\n\n' + body['title'] + '\n\n'
        report += 'Evidence and deterministic results:\n' + json.dumps(evidence, indent=2, allow_nan=False)
        report += '\n\nFindings (hypotheses are not established causes):\n' + json.dumps(body['findings'], indent=2)
        report += '\n\nNo live change was made. Next: operator review; live behavior remains unverified.\n'
        data = {'manifest': manifest, 'report': report}
        # Reserve envelope/headroom before accepting an investigation revision.
        if len(encode(data).encode()) > LIMITS['artifact_bytes'] - 4096:
            raise Fault('LIMIT_EXCEEDED')
        return data

    def ds_add_finding(self, deployment_id, investigation_id, expected_revision,
                       kind, text, evidence_ids, *, db=None):
        if kind not in ('observation', 'hypothesis', 'note'):
            raise Fault('INVALID_ARGUMENT')
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise Fault('INVALID_ARGUMENT')
        if not isinstance(investigation_id, str) or len(investigation_id) > 160:
            raise Fault('INVALID_ARGUMENT')
        evidence = self._evidence(db, evidence_ids)
        row = db.execute('SELECT revision,body FROM investigations WHERE id=?', (investigation_id,)).fetchone()
        if row is None:
            raise Fault('SOURCE_UNAVAILABLE')
        if type(expected_revision) is not int or row[0] != expected_revision:
            raise Fault('STALE_REVISION')
        body = json.loads(row[1])
        if body['deployment_id'] != self.principal.deployment_id:
            raise Fault('PERMISSION_DENIED')
        if len(body['findings']) >= 32:
            raise Fault('LIMIT_EXCEEDED')
        body['findings'].append({'kind': kind, 'text': text, 'evidence_ids': evidence,
                                 'author': self.principal.name,
                                 'at': datetime.now(timezone.utc).isoformat()})
        body['evidence_ids'] = list(dict.fromkeys(body['evidence_ids'] + evidence))
        if len(body['evidence_ids']) > 32:
            raise Fault('LIMIT_EXCEEDED')
        revision = expected_revision + 1
        self._render_export(db, body, revision, investigation_id)
        db.execute('UPDATE investigations SET revision=?,body=? WHERE id=? AND revision=?',
                   (revision, encode(body), investigation_id, expected_revision))
        return {'investigation_id': investigation_id, 'revision': revision}
