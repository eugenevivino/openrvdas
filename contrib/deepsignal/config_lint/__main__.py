"""Command line interface for the cruise configuration linter."""

import argparse
import sys

import yaml

from . import lint


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lint an OpenRVDAS cruise YAML file.")
    parser.add_argument("cruise_yaml", help="cruise definition to inspect")
    parser.add_argument("--root", help="required root for LogfileWriter paths")
    args = parser.parse_args(argv)
    try:
        with open(args.cruise_yaml, "r", encoding="utf-8") as source:
            definition = yaml.safe_load(source)
        if not isinstance(definition, dict):
            raise ValueError("top-level YAML value must be a mapping")
    except (OSError, ValueError, yaml.YAMLError) as error:
        print("Unable to lint %s: %s" % (args.cruise_yaml, error), file=sys.stderr)
        return 2

    findings = lint(definition, root=args.root)
    for item in findings:
        print("%s %s: %s Fix: %s" % (
            item["level"].upper(), item["where"], item["message"], item["fix"]
        ))
    return 1 if any(item["level"] == "error" for item in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
