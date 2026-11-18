"""Shared helpers for passive discovery."""

import string


def text_sample(payload):
    """Return a safe display form for at most 200 bytes."""
    payload = payload[:200]
    decoded = payload.decode("utf-8", "replace")
    printable = sum(char in string.printable for char in decoded)
    if decoded and printable / len(decoded) >= 0.9:
        return decoded.rstrip("\r\n")
    return payload.hex()


def split_lines(payload):
    """Decode payload without hiding malformed input."""
    return payload.decode("utf-8", "replace").splitlines()
