"""Append-only, hash-chained JSONL audit records."""
import hashlib
import hmac
import json
import os


ZERO = "0" * 64


def _compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class AuditLog:
    def __init__(self, path, sign_key=None):
        self.path = path
        self.sign_key = sign_key

    def append(self, record):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        previous = ZERO
        count = 0
        try:
            with open(self.path, "rb") as source:
                for line in source:
                    previous = hashlib.sha256(line).hexdigest()
                    count += 1
        except FileNotFoundError:
            pass
        value = dict(record)
        value["prev_hash"] = previous
        if self.sign_key:
            payload = _compact(value).encode()
            value["sig"] = hmac.new(self.sign_key, payload,
                                    hashlib.sha256).hexdigest()
        line = (_compact(value) + "\n").encode()
        with open(self.path, "ab") as target:
            target.write(line)
        with open(self.path + ".head", "w", encoding="ascii") as head:
            head.write("%d %s" % (count + 1, hashlib.sha256(line).hexdigest()))
        return value


def verify(path, sign_key=None):
    previous = ZERO
    records = 0
    first_break = None
    try:
        with open(path, "rb") as source:
            lines = source.readlines()
    except FileNotFoundError:
        return {"ok": False, "records": 0, "first_break": 1}
    for number, line in enumerate(lines, 1):
        try:
            value = json.loads(line)
            if value.get("prev_hash") != previous:
                first_break = number
                break
            if sign_key is not None:
                signature = value.pop("sig", None)
                expected = hmac.new(sign_key, _compact(value).encode(),
                                    hashlib.sha256).hexdigest()
                if not hmac.compare_digest(signature or "", expected):
                    first_break = number
                    break
            previous = hashlib.sha256(line).hexdigest()
            records += 1
        except (ValueError, TypeError):
            first_break = number
            break
    try:
        with open(path + ".head", encoding="ascii") as source:
            expected_count, expected_hash = source.read().split()
        if first_break is None and (int(expected_count) != len(lines) or
                                    (lines and hashlib.sha256(lines[-1]).hexdigest()
                                     != expected_hash)):
            first_break = min(len(lines) + 1, int(expected_count))
    except (FileNotFoundError, ValueError):
        pass
    return {"ok": first_break is None, "records": records,
            "first_break": first_break}
