"""Read-only discovery for explicit TCP and HTTP targets."""

import socket
import urllib.request

from contrib.deepsignal.discovery.common import split_lines


def scan_tcp(target, listen_s=3, connector=socket.create_connection):
    host, port_text = target.rsplit(":", 1)
    with connector((host, int(port_text)), timeout=listen_s) as stream:
        stream.settimeout(listen_s)
        payload = stream.recv(65536)
    lines = split_lines(payload)
    return {"transport": "tcp", "port": target, "baud": None, "status": "live",
            "lines_per_second": len(lines) / listen_s, "sample_lines": lines[:5],
            "capture_lines": lines[:200], "nmea_talkers": [], "nmea_sentences": []}


def scan_http(url, listen_s=3, url_opener=urllib.request.urlopen):
    request = urllib.request.Request(url, method="GET")
    with url_opener(request, timeout=listen_s) as response:
        lines = split_lines(response.read(65536))
    return {"transport": "http", "port": url, "baud": None, "status": "live",
            "lines_per_second": None, "sample_lines": lines[:5],
            "capture_lines": lines[:200], "nmea_talkers": [], "nmea_sentences": []}
