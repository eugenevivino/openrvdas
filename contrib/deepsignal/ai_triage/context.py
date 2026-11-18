"""Build a bounded deterministic context pack."""
import json

from contrib.deepsignal.ai_triage.redact import redact


def build_pack(snapshot, max_context_tokens=6000):
    allowed = ("stream", "chain", "affected_outputs", "transitions", "timeline",
               "time_health", "failing_stage", "runbook_causes", "incidents",
               "refs", "token", "email")
    selected = {key: snapshot[key] for key in allowed if key in snapshot}
    pack, counts = redact(selected,
                          snapshot.get("held_fields"),
                          snapshot.get("eez_inside", False),
                          snapshot.get("eez_held_fields"))
    limit = max_context_tokens * 4
    while len(json.dumps(pack, sort_keys=True)) > limit and pack:
        longest = max(pack, key=lambda key: len(json.dumps(pack[key])))
        value = pack[longest]
        if isinstance(value, str) and len(value) > 8:
            excess = len(json.dumps(pack, sort_keys=True)) - limit
            pack[longest] = value[:max(0, len(value) - excess - 3)] + "..."
        elif isinstance(value, list) and value:
            value.pop()
        else:
            del pack[longest]
    return pack, counts
