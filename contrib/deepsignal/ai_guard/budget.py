"""Persistent, generic period budgets."""
import datetime
import json
import os
import tempfile
import uuid


class BudgetMeter:
    def __init__(self, path, caps):
        self.path = path
        self.caps = caps

    def _periods(self):
        now = datetime.datetime.now(datetime.UTC)
        return {"day": now.strftime("%Y-%m-%d"),
                "month": now.strftime("%Y-%m")}

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as source:
                return json.load(source)
        except FileNotFoundError:
            return {"usage": {}, "reservations": {}}

    def _write(self, state):
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, text=True)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as target:
                json.dump(state, target, sort_keys=True)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def check_and_reserve(self, cost, unit="usd", scope="default"):
        if cost < 0:
            raise ValueError("cost must be zero or greater")
        state = self._read()
        periods = self._periods()
        keys = []
        for period, marker in periods.items():
            cap = self.caps.get(period, {}).get(unit)
            key = "%s:%s:%s:%s" % (scope, unit, period, marker)
            if cap is not None and state["usage"].get(key, 0) + cost > cap:
                return False
            keys.append(key)
        reservation = uuid.uuid4().hex
        state["reservations"][reservation] = {"cost": cost, "keys": keys}
        for key in keys:
            state["usage"][key] = state["usage"].get(key, 0) + cost
        self._write(state)
        return reservation

    def settle(self, reservation, actual):
        state = self._read()
        item = state["reservations"].pop(reservation, None)
        if item is None:
            raise ValueError("unknown reservation")
        adjustment = actual - item["cost"]
        for key in item["keys"]:
            state["usage"][key] = max(0, state["usage"].get(key, 0) + adjustment)
        self._write(state)
