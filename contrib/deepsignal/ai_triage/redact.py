"""Recursive privacy filtering for outbound context packs."""
import re


EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d .()-]{7,}\d)")
SECRET_KEYS = re.compile(r"(?:password|passwd|secret|token|api.?key|private.?key)", re.I)
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


def redact(value, held_fields=None, eez_inside=False, eez_held_fields=None):
    held_fields = set(held_fields or ())
    eez_held_fields = set(eez_held_fields or ())
    counts = {"credentials": 0, "emails": 0, "phones": 0,
              "held_back": 0, "eez_held_back": 0, "positions_rounded": 0}

    def clean(item, key=None):
        if isinstance(item, dict):
            output = {}
            for child_key, child in item.items():
                if child_key in held_fields:
                    counts["held_back"] += 1
                elif eez_inside and child_key in eez_held_fields:
                    counts["eez_held_back"] += 1
                elif SECRET_KEYS.search(str(child_key)):
                    counts["credentials"] += 1
                else:
                    output[child_key] = clean(child, child_key)
            return output
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, str):
            if PRIVATE_KEY.search(item):
                counts["credentials"] += 1
                return "[REDACTED]"
            replaced, email_count = EMAIL.subn("[REDACTED EMAIL]", item)
            replaced, phone_count = PHONE.subn("[REDACTED PHONE]", replaced)
            counts["emails"] += email_count
            counts["phones"] += phone_count
            return replaced
        if key in ("latitude", "longitude", "lat", "lon") and isinstance(
                item, (float, int)) and eez_inside:
            counts["positions_rounded"] += 1
            return round(item, 2)
        return item

    return clean(value), counts
