"""Event-only triage trigger state."""
import hashlib


def signature(stream, failing_stage, evidence_kinds):
    value = "|".join([stream, failing_stage] + sorted(evidence_kinds))
    return hashlib.sha256(value.encode()).hexdigest()


class TriggerManager:
    def __init__(self, hold_s=60, digest_times=None):
        self.hold_s = hold_s
        self.digest_times = set(digest_times or
                                ["0400", "0800", "1200", "1600", "2000", "0000"])
        self.pending = {}
        self.sent_digests = set()

    def transition(self, stream, state, timestamp):
        if state not in ("DEGRADED", "FAILED"):
            self.pending.pop(stream, None)
            return False
        first = self.pending.setdefault(stream, timestamp)
        return timestamp - first >= self.hold_s

    def alert(self, stream, level):
        return level in ("A1", "A2")

    def request(self, stream):
        return True

    def digest(self, ship_time, date):
        key = (date, ship_time)
        if ship_time not in self.digest_times or key in self.sent_digests:
            return False
        self.sent_digests.add(key)
        return True
