"""Event-triggered triage orchestration."""
import datetime
import hashlib
import json
import os
import time
import uuid

from contrib.deepsignal.ai_guard.audit import AuditLog
from contrib.deepsignal.ai_guard.budget import BudgetMeter
from contrib.deepsignal.ai_triage import context, schema
from contrib.deepsignal.ai_triage.triggers import signature


class TriageService:
    def __init__(self, state_dir, api_model=None, local_model=None,
                 api_enabled=True, local_enabled=False, cache_hours=6,
                 max_context_tokens=6000, caps=None):
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self.api_model = api_model
        self.local_model = local_model
        self.api_enabled = api_enabled
        self.local_enabled = local_enabled
        self.cache_hours = cache_hours
        self.max_context_tokens = max_context_tokens
        self.link_up = True
        self.cache = {}
        self.queue_path = os.path.join(state_dir, "queue.jsonl")
        self.timeline = AuditLog(os.path.join(state_dir, "timeline.jsonl"))
        self.outcomes_path = os.path.join(state_dir, "outcomes.jsonl")
        self.meter = BudgetMeter(os.path.join(state_dir, "budget.json"), caps or {
            "day": {"usd": 2}, "month": {"usd": 30}})

    def _fallback(self, stream, snapshot, label="no AI used"):
        stage = snapshot.get("failing_stage") or "unknown stage"
        causes = snapshot.get("runbook_causes") or []
        return {"summary": "%s is the first failing stage." % stage,
                "causes": [{"cause": cause, "likelihood": "medium",
                            "evidence": []} for cause in causes[:3]],
                "checks": [{"step": "Follow the %s runbook" % stage,
                            "kind": "look"}], "cannot_tell": not bool(causes),
                "confidence": 0, "label": label, "stream": stream}

    def _enqueue(self, request):
        entries = []
        try:
            with open(self.queue_path, encoding="utf-8") as source:
                entries = [json.loads(line) for line in source if line.strip()]
        except FileNotFoundError:
            pass
        entries.append(request)
        entries = entries[-50:]
        with open(self.queue_path, "w", encoding="utf-8") as target:
            for entry in entries:
                target.write(json.dumps(entry, sort_keys=True) + "\n")

    def _call(self, model, pack):
        last_error = None
        for unused in range(2):
            try:
                response = model.complete(pack)
                decoded = json.loads(response["content"])
                refs = {item["id"] for item in pack.get("refs", [])}
                return schema.validate(decoded, refs), response.get("usage", {})
            except (ValueError, KeyError, TypeError, OSError) as error:
                last_error = error
        raise last_error

    def briefing(self, stream, snapshot):
        pack, removals = context.build_pack(snapshot, self.max_context_tokens)
        evidence = [item.get("kind", item.get("id", ""))
                    for item in pack.get("refs", [])]
        pack_signature = signature(stream, snapshot.get("failing_stage", ""), evidence)
        cached = self.cache.get(pack_signature)
        now = time.time()
        if cached and now - cached[0] <= self.cache_hours * 3600:
            answer = dict(cached[1])
            answer["same_as_before"] = True
            return answer
        label = None
        usage = {}
        started = time.monotonic()
        answer = None
        if self.api_enabled and self.api_model and self.link_up:
            reservation = self.meter.check_and_reserve(0, "usd", "ship")
            if reservation:
                try:
                    answer, usage = self._call(self.api_model, pack)
                    self.meter.settle(reservation, 0)
                    label = "API model"
                except (ValueError, KeyError, TypeError, OSError):
                    self.meter.settle(reservation, 0)
        if answer is None and self.local_enabled and self.local_model:
            try:
                answer, usage = self._call(self.local_model, pack)
                label = "local model"
            except (ValueError, KeyError, TypeError, OSError):
                pass
        if answer is None:
            if self.api_enabled and self.api_model and not self.link_up:
                self._enqueue({"stream": stream, "snapshot": snapshot,
                               "queued_at": datetime.datetime.now(
                                   datetime.UTC).isoformat()})
                label = "AI pending"
            else:
                label = "no AI used"
            answer = self._fallback(stream, snapshot, label)
        briefing_id = uuid.uuid4().hex
        answer.update({"label": label, "briefing_id": briefing_id,
                       "same_as_before": False})
        audit = {"kind": "ai_briefing", "briefing_id": briefing_id,
                 "pack_hash": hashlib.sha256(json.dumps(
                     pack, sort_keys=True).encode()).hexdigest(),
                 "model": label, "tokens": usage, "cost": 0,
                 "latency": time.monotonic() - started, "output": answer,
                 "removals": removals}
        self.timeline.append(audit)
        self.cache[pack_signature] = (now, dict(answer))
        return answer

    def reconnect(self, still_open):
        try:
            with open(self.queue_path, encoding="utf-8") as source:
                entries = [json.loads(line) for line in source if line.strip()]
        except FileNotFoundError:
            return []
        self.link_up = True
        results = [self.briefing(item["stream"], item["snapshot"])
                   for item in entries if still_open(item["stream"])]
        open(self.queue_path, "w", encoding="utf-8").close()
        return results

    def record_outcome(self, briefing_id, worked, note, who):
        record = {"briefing_id": briefing_id, "worked": worked,
                  "note": note, "who": who}
        with open(self.outcomes_path, "a", encoding="utf-8") as target:
            target.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def propose_runbook_updates(self):
        try:
            with open(self.outcomes_path, encoding="utf-8") as source:
                records = [json.loads(line) for line in source if line.strip()]
        except FileNotFoundError:
            records = []
        return "\n".join(
            "+ %s" % item["note"] for item in records
            if item.get("worked") != "none")
