"""Read-only discovery of recently modified, growing files."""

import os
import time


def scan_files(directory, now=None):
    """Report regular files modified within the last hour."""
    now = now or time.time()
    results = []
    for root, unused_dirs, names in os.walk(directory):
        del unused_dirs
        for name in names:
            path = os.path.join(root, name)
            stat = os.stat(path)
            age = now - stat.st_mtime
            if age > 3600 or not os.path.isfile(path):
                continue
            with open(path, "rb") as source:
                source.seek(max(0, stat.st_size - 8192))
                lines = source.read().decode("utf-8", "replace").splitlines()
            results.append({"transport": "file", "port": path, "baud": None,
                            "lines_per_second": None, "sample_lines": lines[-5:],
                            "capture_lines": lines[-200:], "nmea_talkers": [],
                            "nmea_sentences": [], "status": "recent",
                            "bytes": stat.st_size, "modified_age_s": age})
    return results
