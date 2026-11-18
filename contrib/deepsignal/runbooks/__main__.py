"""Command line interface for vessel runbooks."""

import argparse
import json
from pathlib import Path
import sys

import yaml

from . import runbooks


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage vessel alarm runbooks")
    parser.add_argument("--directory", type=Path, required=True,
                        help="directory containing stream Markdown runbooks")
    commands = parser.add_subparsers(dest="command", required=True)
    draft_parser = commands.add_parser("draft", help="draft a runbook from a cruise definition")
    draft_parser.add_argument("stream")
    draft_parser.add_argument("cruise", type=Path)
    draft_parser.add_argument("--history", type=Path)
    check_parser = commands.add_parser("check", help="check configured streams")
    check_parser.add_argument("config", type=Path)
    show_parser = commands.add_parser("show", help="show alarm-safe runbook JSON")
    show_parser.add_argument("stream")
    show_parser.add_argument("--stage")
    args = parser.parse_args(argv)

    if args.command == "draft":
        cruise = yaml.safe_load(args.cruise.read_text(encoding="utf-8"))
        history = (yaml.safe_load(args.history.read_text(encoding="utf-8"))
                   if args.history else None)
        metadata = runbooks.draft(args.stream, cruise, history)
        args.directory.mkdir(parents=True, exist_ok=True)
        path = args.directory / f"{args.stream}.md"
        path.write_text(runbooks.to_markdown(metadata), encoding="utf-8")
        print(path)
        return 0
    if args.command == "check":
        config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("streams"), list):
            parser.error("streams: saw a missing or non-list value; expected a list; "
                         "for example streams: [tsg1].")
        findings = runbooks.check(args.directory, config["streams"])
        print("\n".join(findings))
        return bool(findings)
    runbooks.load_all(args.directory)
    print(json.dumps(runbooks.for_alarm(args.stream, args.stage), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
