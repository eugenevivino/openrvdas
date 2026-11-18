"""Command line report for continuous archive readiness."""

import argparse
import json

from .archive_ready import load_expected, scan


def main(argv=None):
    parser = argparse.ArgumentParser(description="Report continuous archive readiness")
    parser.add_argument("root", help="archive root to scan")
    parser.add_argument("expected", help="expected dataset YAML")
    parser.add_argument("metadata", help="cruise metadata YAML")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)
    expected = load_expected(args.expected)
    metadata = load_expected_metadata(args.metadata)
    result = scan(args.root, expected, metadata)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{'DATASET':24} {'FILES':>7} {'COVERAGE':>10}")
        for dataset in result["datasets"]:
            print(f"{dataset['name'][:24]:24} {len(dataset['files']):7d} "
                  f"{dataset['coverage_percent']:9.2f}%")
        print(f"Checks: {len(result['checks'])}")
        for check in result["checks"]:
            print(f"{check['code']}: {check['explanation']}")
    return 1 if result["checks"] else 0


def load_expected_metadata(path):
    import yaml
    with open(path, encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(
            f"Setting 'cruise metadata' was {value!r}; expected a mapping; "
            "for example cruise_id: NBP1406."
        )
    return value


if __name__ == "__main__":
    raise SystemExit(main())
