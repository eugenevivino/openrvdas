"""Safely identify local serial streams without transmitting bytes."""

import glob
import re
import time


BAUD_RATES = [4800, 9600, 19200, 38400, 57600, 115200]
NMEA_PATTERN = re.compile(rb"\$([A-Z]{2})([A-Z]{3}),[^\r\n]*\*([0-9A-Fa-f]{2})")


def candidate_ports(port_lister=None, globber=glob.glob):
    """Return the union of pyserial and conventional Linux port names."""
    if port_lister is None:
        from serial.tools import list_ports
        port_lister = list_ports.comports
    ports = {getattr(item, "device", str(item)) for item in port_lister()}
    for pattern in ("/dev/ttyS*", "/dev/ttyUSB*", "/dev/ttyACM*"):
        ports.update(globber(pattern))
    return sorted(ports)


def _nmea_ids(payload):
    talkers, sentences, valid = set(), set(), 0
    for match in NMEA_PATTERN.finditer(payload):
        sentence = match.group(0)
        body, claimed = sentence[1:].rsplit(b"*", 1)
        checksum = 0
        for byte in body:
            checksum ^= byte
        if checksum == int(claimed, 16):
            valid += 1
            talkers.add(match.group(1).decode("ascii"))
            sentences.add(match.group(2).decode("ascii"))
    return sorted(talkers), sorted(sentences), valid


def _score(payload):
    printable = sum(byte in b"\t\n\r" or 32 <= byte <= 126 for byte in payload)
    share = printable / len(payload) if payload else 0.0
    endings = payload.count(b"\n") + payload.count(b"\r")
    talkers, sentences, valid = _nmea_ids(payload)
    return (share, endings, valid), talkers, sentences


def scan_port(port, listen_s=3, opener=None, baud_rates=None, clock=time.monotonic):
    """Try known baud rates and describe one serial port, never writing to it."""
    del clock  # opener timeouts bound real reads; fakes terminate by returning empty bytes.
    if opener is None:
        import serial
        opener = serial.Serial
    attempts = []
    busy_count = 0
    for baud in baud_rates or BAUD_RATES:
        handle = None
        try:
            handle = opener(port=port, baudrate=baud, timeout=listen_s)
            # A single bounded read prevents an empty follow-up read from doubling
            # the requested listening window on real pyserial objects.
            payload = handle.read(65536)
        except (OSError, IOError):
            busy_count += 1
            continue
        finally:
            if handle is not None:
                handle.close()
        score, talkers, sentences = _score(payload)
        attempts.append((score, baud, payload, talkers, sentences))
    base = {"transport": "serial", "port": port, "baud": None,
            "lines_per_second": 0.0, "sample_lines": [], "nmea_talkers": [],
            "nmea_sentences": []}
    if not attempts and busy_count:
        return dict(base, status="busy: skipped")
    populated = [attempt for attempt in attempts if attempt[2]]
    if not populated:
        return dict(base, status="silent: may need polling")
    best = max(populated, key=lambda item: item[0])
    if best[0][0] < 0.9:
        return dict(base, status="unreadable at all tried rates")
    lines = best[2].decode("utf-8", "replace").splitlines()
    return dict(base, baud=best[1], lines_per_second=len(lines) / listen_s,
                sample_lines=lines[:5], capture_lines=lines[:200],
                nmea_talkers=best[3], nmea_sentences=best[4], status="live")
