"""Shared guided-setup engine."""
import errno
import datetime
import json
import time
import urllib.error

import yaml

from contrib.deepsignal.ai_triage.context import build_pack
from contrib.deepsignal.ai_triage import vault as key_vault


VAULT_REQUIRED = key_vault.VAULT_REQUIRED


def _read_config(path):
    try:
        with open(path, encoding="utf-8") as source:
            return yaml.safe_load(source) or {}
    except FileNotFoundError:
        return {}


def _write_config(path, value):
    with open(path, "w", encoding="utf-8") as target:
        yaml.safe_dump(value, target, sort_keys=True)


def _log_choice(path, record):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as target:
        target.write(json.dumps(record, sort_keys=True) + "\n")


def opt_in(path, by, cruise_id, audit_path=None, now=None):
    """Record the sixth setup step, which alone enables outbound calls."""
    value = _read_config(path)
    api = value.setdefault("api", {})
    choice = {"by": by, "at": now or datetime.datetime.now(
        datetime.UTC).isoformat(), "cruise_id": cruise_id}
    api["opt_in"] = choice
    _write_config(path, value)
    _log_choice(audit_path, {"action": "opt_in", **choice})
    return value


def opt_out(path, by, reason, audit_path=None, now=None):
    """Disable outbound calls and retain an append-only decision record."""
    value = _read_config(path)
    value.setdefault("api", {}).pop("opt_in", None)
    at = now or datetime.datetime.now(datetime.UTC).isoformat()
    _write_config(path, value)
    _log_choice(audit_path, {"action": "opt_out", "by": by, "at": at,
                             "reason": reason})
    return value


def providers():
    return [{"name": "OpenAI-compatible",
             "url": "https://api.openai.com/v1/chat/completions",
             "shape": "chat/completions"},
            {"name": "Anthropic", "url": "https://api.anthropic.com/v1/messages",
             "shape": "messages"}]


def store_key(provider, key, vault=None, vault_loader=key_vault.installed_vault):
    protector = key_vault.put(provider, key, vault, vault_loader)
    return {"ok": True, "protector": protector,
            "message": "Key stored using %s protector" % protector}


def load_key(provider, vault=None, vault_loader=key_vault.installed_vault):
    return key_vault.get(provider, vault, vault_loader)


def set_caps(path, daily_usd, monthly_usd, prices):
    if daily_usd < 0:
        raise ValueError(
            "api.max_usd_per_day saw %s; expected zero or greater, "
            "for example 2" % daily_usd)
    if monthly_usd < daily_usd:
        raise ValueError(
            "api.max_usd_per_month saw %s; expected at least the daily cap, "
            "for example 30" % monthly_usd)
    value = {"api": {"max_usd_per_day": daily_usd,
                     "max_usd_per_month": monthly_usd, "prices": prices}}
    with open(path, "w", encoding="utf-8") as target:
        yaml.safe_dump(value, target, sort_keys=True)
    return value


def test_call(model, meter=None):
    if meter and not meter.check_and_reserve(0, "usd", "ship"):
        return {"ok": False, "error": "budget reached"}
    started = time.monotonic()
    try:
        result = model.complete({"prompt": "Reply only with OK"}, 8)
        return {"ok": True, "error": None,
                "latency": time.monotonic() - started,
                "tokens": result.get("usage", {}), "cost": 0}
    except urllib.error.HTTPError as error:
        message = "bad key" if error.code == 401 else "provider error %s" % error.code
    except urllib.error.URLError as error:
        message = ("proxy unreachable" if "proxy" in str(error).lower()
                   else "network name lookup failed")
    except OSError as error:
        message = ("network name lookup failed"
                   if error.errno in (errno.EAI_NONAME, -2) else str(error))
    except ValueError as error:
        message = str(error)
    except key_vault.VaultUnavailable:
        message = VAULT_REQUIRED
    return {"ok": False, "error": message,
            "latency": time.monotonic() - started, "tokens": {}, "cost": 0}


def preview(snapshot, max_context_tokens=6000):
    pack, removals = build_pack(snapshot, max_context_tokens)
    return {"pack": pack, "removals": removals}
