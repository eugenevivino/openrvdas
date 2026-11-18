"""Read-only HTTP API backed by an OpenRVDAS CachedDataServer."""

import argparse
import csv
import datetime
import io
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from contrib.deepsignal.rest_api.source import CDSSource, SourceUnavailable

MAX_SECONDS = 86400
MAX_POINTS = 20000
MAX_FIELDS = 20


def _json_bytes(value):
    """Serialize JSON while escaping HTML delimiters if embedded in a page."""
    result = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return result.replace("<", "\\u003c").replace(">", "\\u003e").encode("utf-8")


def _query_integer(query, name, default, maximum, example):
    raw = query.get(name, [str(default)])[0]
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(
            "%s saw %r; expected an integer from 1 through %d; example: %s=%s"
            % (name, raw, maximum, name, example)) from error
    if value < 1 or value > maximum:
        raise ValueError(
            "%s saw %r; expected a value from 1 through %d; example: %s=%s"
            % (name, raw, maximum, name, example))
    return value


class RestAPIHandler(BaseHTTPRequestHandler):
    """GET-only REST request handler."""

    server_version = "DeepSignalREST/1"

    def log_message(self, format_string, *args):
        """Use the embedding application's logging rather than stderr."""

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, value):
        self._send(status, _json_bytes(value))

    def _plain(self, status, message):
        self._send(status, message + "\n", "text/plain; charset=utf-8")

    def _known_fields(self):
        return self.server.source.fields()

    def _require_known(self, names):
        known = set(self._known_fields())
        for name in names:
            if name not in known:
                self._plain(404, "unknown field %r" % name)
                return False
        return True

    def do_GET(self):
        """Dispatch a version-one API request."""
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            if parsed.path == "/api/v1/fields":
                self._fields()
            elif parsed.path == "/api/v1/latest":
                self._latest(query)
            elif parsed.path == "/api/v1/series":
                self._series(query)
            elif parsed.path == "/api/v1/health":
                self._health()
            else:
                self._plain(404, "unknown endpoint %r" % parsed.path)
        except ValueError as error:
            self._plain(400, str(error))
        except SourceUnavailable as error:
            self._plain(503, str(error))

    def _fields(self):
        names = self._known_fields()
        metadata = self.server.source.describe(names)
        fields = []
        for name in names:
            item = {"name": name}
            item.update(metadata.get(name, {}))
            fields.append(item)
        self._json(200, {"fields": fields})

    def _latest(self, query):
        raw = query.get("fields", [""])[0]
        names = [name for name in raw.split(",") if name]
        if not names:
            raise ValueError(
                "fields saw %r; expected 1 through 20 comma-separated names; "
                "example: fields=air_temp,wind_speed" % raw)
        if len(names) > MAX_FIELDS:
            raise ValueError(
                "fields saw %d names; expected at most 20; example: fields=air_temp,wind_speed"
                % len(names))
        if not self._require_known(names):
            return
        result = {}
        now = self.server.clock()
        for name in names:
            points = self.server.source.series(name, -1)
            if points:
                timestamp, value = points[-1]
                result[name] = {"value": value, "timestamp": timestamp,
                                "age": max(0, now - timestamp)}
            else:
                result[name] = {"value": None, "timestamp": None, "age": None}
        self._json(200, {"fields": result})

    def _series(self, query):
        name = query.get("field", [""])[0]
        if not name:
            raise ValueError(
                "field saw an empty value; expected one field name; example: field=air_temp")
        seconds = _query_integer(query, "seconds", 600, MAX_SECONDS, 600)
        max_points = _query_integer(query, "max_points", 2000, MAX_POINTS, 2000)
        if not self._require_known([name]):
            return
        points = list(self.server.source.series(name, seconds))
        step = max(1, math.ceil(len(points) / max_points))
        points = points[::step]
        if query.get("format", ["json"])[0] == "csv":
            self._series_csv(points)
            return
        self._json(200, {"field": name, "seconds": seconds, "decimated": step,
                         "points": points})

    def _series_csv(self, points):
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("time", "value"))
        for timestamp, value in points:
            instant = datetime.datetime.fromtimestamp(
                timestamp, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            writer.writerow((instant, value))
        self._send(200, output.getvalue(), "text/csv; charset=utf-8")

    def _health(self):
        try:
            self._known_fields()
        except SourceUnavailable:
            self._json(503, {"source_reachable": False})
            return
        self._json(200, {"source_reachable": True})

    def _method_not_allowed(self):
        self._plain(405, "method not allowed; this read-only API accepts GET only")

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_HEAD = _method_not_allowed
    do_OPTIONS = _method_not_allowed


def create_server(host, port, source, clock=time.time):
    """Create, but do not start, a configured REST server."""
    server = ThreadingHTTPServer((host, port), RestAPIHandler)
    server.source = source
    server.clock = clock
    return server


def main(argv=None):
    """Run the REST server from the command line."""
    parser = argparse.ArgumentParser(description="Serve read-only OpenRVDAS data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--cds", default="ws://127.0.0.1:8766")
    args = parser.parse_args(argv)
    server = create_server(args.host, args.port, CDSSource(args.cds))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
