"""Passive local UDP listener."""

import socket
import time


def scan_udp_port(port, listen_s=3, opener=None, clock=time.monotonic):
    """Bind a local UDP port and describe datagrams received during the window."""
    opener = opener or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
    handle = None
    base = {"transport": "udp", "port": port, "baud": None,
            "lines_per_second": 0.0, "sample_lines": [], "nmea_talkers": [],
            "nmea_sentences": []}
    try:
        handle = opener()
        handle.bind(("", port))
        handle.settimeout(listen_s)
        start = clock()
        lines = []
        while len(lines) < 200:
            try:
                payload, unused_address = handle.recvfrom(65535)
                del unused_address
            except (TimeoutError, socket.timeout):
                break
            lines.extend(payload.decode("utf-8", "replace").splitlines() or [""])
        elapsed = max(clock() - start, 1e-9)
        return dict(base, status="live" if lines else "silent",
                    lines_per_second=len(lines) / elapsed,
                    sample_lines=lines[:5], capture_lines=lines[:200])
    except OSError as error:
        return dict(base, status="busy: skipped", error=str(error))
    finally:
        if handle is not None:
            handle.close()
