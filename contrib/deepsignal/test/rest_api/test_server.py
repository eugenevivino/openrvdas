"""Tests for the DeepSignal read-only REST API."""

import json
import threading
import unittest
import urllib.error
import urllib.request

from contrib.deepsignal.rest_api.server import create_server
from contrib.deepsignal.rest_api.source import SourceUnavailable


class FakeSource:
    """Deterministic in-memory data source used by HTTP tests."""

    def __init__(self, unavailable=False):
        self.unavailable = unavailable
        self.data = {
            "air_temp": [(1000.0, 10.0), (1001.0, 11.0),
                         (1002.0, 12.0), (1003.0, 13.0), (1004.0, 14.0)],
            "<script>": [(1004.0, "safe")],
        }
        self.metadata = {"air_temp": {"units": "degC"}, "<script>": {}}

    def _check(self):
        if self.unavailable:
            raise SourceUnavailable("CDS is unreachable")

    def fields(self):
        self._check()
        return list(self.data)

    def describe(self, names):
        self._check()
        return {name: self.metadata.get(name, {}) for name in names}

    def series(self, name, seconds):
        self._check()
        return self.data[name]


class RestAPITest(unittest.TestCase):
    def setUp(self):
        self.server = create_server("127.0.0.1", 0, FakeSource(), clock=lambda: 1010.0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, method="GET", data=None):
        request = urllib.request.Request(self.base + path, data=data, method=method)
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            response = error
        return response.status, dict(response.headers), response.read().decode("utf-8")

    def test_fields_includes_metadata(self):
        status, headers, body = self.request("/api/v1/fields")
        self.assertEqual(200, status)
        self.assertEqual("no-store", headers["Cache-Control"])
        self.assertEqual(
            [{"name": "air_temp", "units": "degC"}, {"name": "<script>"}],
            json.loads(body)["fields"])
        self.assertIn("\\u003cscript\\u003e", body)

    def test_latest_shape_and_age(self):
        status, _, body = self.request("/api/v1/latest?fields=air_temp")
        self.assertEqual(200, status)
        self.assertEqual({"value": 14.0, "timestamp": 1004.0, "age": 6.0},
                         json.loads(body)["fields"]["air_temp"])

    def test_series_shape_and_decimation(self):
        status, _, body = self.request(
            "/api/v1/series?field=air_temp&seconds=600&max_points=2")
        self.assertEqual(200, status)
        result = json.loads(body)
        self.assertEqual("air_temp", result["field"])
        self.assertEqual(3, result["decimated"])
        self.assertEqual([[1000.0, 10.0], [1003.0, 13.0]], result["points"])

    def test_series_csv(self):
        status, headers, body = self.request(
            "/api/v1/series?field=air_temp&seconds=10&format=csv")
        self.assertEqual(200, status)
        self.assertTrue(headers["Content-Type"].startswith("text/csv"))
        first_rows = body.splitlines()[0] + "\r\n" + body.splitlines()[1]
        self.assertEqual("time,value\r\n1970-01-01T00:16:40Z,10.0", first_rows)

    def test_budget_refusals(self):
        cases = [
            ("/api/v1/series?field=air_temp&seconds=86401", "seconds", "86400"),
            ("/api/v1/series?field=air_temp&max_points=20001", "max_points", "20000"),
            ("/api/v1/latest?fields=" + ",".join("f%d" % i for i in range(21)),
             "fields", "20"),
        ]
        for path, setting, limit in cases:
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(400, status)
                self.assertIn(setting, body)
                self.assertIn(limit, body)

    def test_unknown_field(self):
        status, _, body = self.request("/api/v1/series?field=missing")
        self.assertEqual(404, status)
        self.assertIn("missing", body)

    def test_health_and_unreachable(self):
        status, _, body = self.request("/api/v1/health")
        self.assertEqual(200, status)
        self.assertEqual({"source_reachable": True}, json.loads(body))
        self.server.source.unavailable = True
        status, _, body = self.request("/api/v1/health")
        self.assertEqual(503, status)
        self.assertEqual({"source_reachable": False}, json.loads(body))
        status, _, body = self.request("/api/v1/fields")
        self.assertEqual(503, status)
        self.assertIn("unreachable", body)

    def test_no_write_method_works(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method):
                status, _, body = self.request("/api/v1/health", method, b"{}")
                self.assertEqual(405, status)
                self.assertIn("GET", body)


if __name__ == "__main__":
    unittest.main()
