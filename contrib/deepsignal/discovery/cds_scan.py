"""CachedDataServer field discovery through the current HTTP API."""

import json
import urllib.request


def scan_cds(target, listen_s=3, url_opener=urllib.request.urlopen):
    url = "http://%s/fields" % target
    request = urllib.request.Request(url, method="GET")
    with url_opener(request, timeout=listen_s) as response:
        fields = json.loads(response.read().decode("utf-8"))
    return {"transport": "cds", "port": target, "baud": None, "status": "live",
            "lines_per_second": None, "sample_lines": [], "capture_lines": [],
            "nmea_talkers": [], "nmea_sentences": [], "fields": fields}
