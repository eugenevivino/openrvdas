"""Command line entry point for Grafana quality pack generation."""

import argparse
from pathlib import Path

import yaml

from . import build


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build OpenRVDAS Grafana quality files")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("cruise_yaml", type=Path)
    build_parser.add_argument("--out", required=True, type=Path)
    build_parser.add_argument("--stale-after-s", default=300, type=float)
    args = parser.parse_args(argv)
    try:
        cruise = yaml.safe_load(args.cruise_yaml.read_text(encoding="utf-8"))
        build(cruise, args.out, {
            "base_dir": Path.cwd(),
            "stale_after_s": args.stale_after_s,
        })
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
