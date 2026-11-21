import tempfile
import unittest
from pathlib import Path
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from contrib.deepsignal.workspace.service import Workspace
from contrib.deepsignal.workspace.http_server import create_app


class FixtureHttp(unittest.TestCase):
    def test_http_and_service_freeze_identical_inputs_and_refuse_foreign_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Workspace(Path(directory) / 'state.sqlite3')
            with TestClient(create_app(service), base_url='http://127.0.0.1:8765') as client:
                token = client.get('/api/workspace/session').json()['token']
                request = {'method': 'ds_query_data', 'arguments': {
                    'deployment_id': 'fixture-vessel', 'stream_id': 'fixture-vessel/temperature',
                    'start': 0, 'end': 6}}
                headers = {'X-DeepSignal-Token': token, 'Origin': 'http://127.0.0.1:8765'}
                result = client.post('/api/workspace/call', json=request, headers=headers)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()['data']['dataset_id'],
                                 service.call(request['method'], request['arguments'])['data']['dataset_id'])
                self.assertEqual(client.post('/api/workspace/call', json=request).status_code, 403)
                headers['Origin'] = 'https://unrelated.invalid'
                self.assertEqual(client.post('/api/workspace/call', json=request, headers=headers).status_code, 403)

    def test_fixture_subscription_rejects_nonobject_request_without_server_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Workspace(Path(directory) / 'state.sqlite3')
            with TestClient(create_app(service), base_url='http://127.0.0.1:8765') as client:
                with client.websocket_connect('/cds-ws') as socket:
                    socket.send_json([])
                    with self.assertRaises(WebSocketDisconnect) as closed:
                        socket.receive_json()
                    self.assertEqual(closed.exception.code, 1008)


if __name__ == '__main__':
    unittest.main()
