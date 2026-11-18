"""Command-line interface for configuration provenance."""

import argparse
import json

from contrib.deepsignal.config_provenance.provenance import ConfigHistory


def main(argv=None):
    parser = argparse.ArgumentParser(description="Track configuration history")
    parser.add_argument("--store", default="/var/lib/deepsignal/config-history/")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("paths", nargs="+")
    snapshot.add_argument("--who", required=True)
    snapshot.add_argument("--note", default="")
    commands.add_parser("log")
    diff = commands.add_parser("diff")
    diff.add_argument("old")
    diff.add_argument("new")
    drift = commands.add_parser("drift")
    drift.add_argument("--baseline", required=True)
    drift.add_argument("current")
    args = parser.parse_args(argv)
    history = ConfigHistory(args.store)
    if args.command == "snapshot":
        result = history.snapshot(args.paths, args.who, args.note)
    elif args.command == "log":
        result = history.log()
    elif args.command == "diff":
        result = history.diff(args.old, args.new)
    else:
        result = history.drift(args.baseline, args.current)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
