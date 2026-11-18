"""Command-line interface for instrument histories."""

import argparse
import datetime
import json

from contrib.deepsignal.instruments.history import InstrumentHistory


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m contrib.deepsignal.instruments")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("file")
    at = commands.add_parser("at")
    at.add_argument("file")
    at.add_argument("field")
    at.add_argument("time")
    args = parser.parse_args(argv)
    history = InstrumentHistory.load(args.file)
    if args.command == "check":
        findings = history.check()
        for finding in findings:
            print(f"{finding['level'].upper()}: {finding['instrument']}: {finding['message']}")
        return 1 if any(item["level"] == "error" for item in findings) else 0
    state = history.instrument_for_field(args.field, args.time)
    print(json.dumps(state, default=_json_default, sort_keys=True))
    return 0 if state is not None else 1


def _json_default(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
