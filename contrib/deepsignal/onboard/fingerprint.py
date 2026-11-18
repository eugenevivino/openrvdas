"""Identify captured instrument text against OpenRVDAS device definitions."""
from dataclasses import dataclass, field
from glob import glob
from typing import Any

import yaml

from logger.utils.record_parser import RecordParser


@dataclass
class Candidate:
    """A device-type match and the observations supporting it."""

    device_type: str
    score: float
    evidence: str
    fields_seen: list[str] = field(default_factory=list)
    sentence_ids: list[str] = field(default_factory=list)
    patterns: Any = None
    metadata: dict = field(default_factory=dict)


def strip_timestamp(line):
    """Remove an ISO OpenRVDAS timestamp, without modifying the payload."""
    first, separator, remainder = str(line).strip().partition(" ")
    if separator and "T" in first and first.endswith("Z"):
        return remainder
    return str(line).strip()


def _definitions():
    definitions = {}
    for filename in sorted(glob("local/devices/*.yaml") + glob("contrib/devices/*.yaml")):
        with open(filename, encoding="utf-8") as stream:
            document = yaml.safe_load(stream) or {}
        for name, value in document.items():
            if isinstance(value, dict) and value.get("category") == "device_type":
                definitions[name] = value
    return definitions


def _sentence_id(payload):
    if payload.startswith("$"):
        return payload.split(",", 1)[0].lstrip("$")
    return payload.split(",", 1)[0]


def _checksum_valid(payload):
    if not payload.startswith("$") or "*" not in payload:
        return True
    body, supplied = payload[1:].rsplit("*", 1)
    checksum = 0
    for character in body:
        checksum ^= ord(character)
    try:
        return checksum == int(supplied[:2], 16)
    except ValueError:
        return False


def identify(lines):
    """Return ranked candidates for capture lines, or a raw fallback."""
    payloads = [strip_timestamp(line) for line in lines if str(line).strip()]
    if not payloads:
        return [_fallback()]
    candidates = []
    for name, definition in _definitions().items():
        patterns = definition.get("format")
        parser = RecordParser(
            record_format="{field_string}", field_patterns=patterns,
            metadata=definition.get("fields", {}), quiet=True,
        )
        parsed = []
        for payload in payloads:
            result = parser.parse_record(payload)
            if result is not None and _checksum_valid(payload):
                parsed.append(result)
        share = len(parsed) / len(payloads)
        if share < 0.8:
            continue
        fields = sorted({key for result in parsed for key in result.get("fields", {})})
        sentence_ids = sorted({_sentence_id(payload) for payload in payloads})
        evidence = f"{len(parsed)} of {len(payloads)} lines parsed as {name}"
        if sentence_ids:
            evidence += " (" + ", ".join(sentence_ids) + ")"
        candidates.append(Candidate(name, share, evidence, fields, sentence_ids,
                                    patterns, definition.get("fields", {})))
    candidates.sort(key=lambda item: (-item.score, item.device_type))
    return candidates or [_fallback()]


def _fallback():
    return Candidate(
        "No known device matched", 0, "No known device matched; using a regex-free raw logger"
    )
