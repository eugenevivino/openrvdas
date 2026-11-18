"""Command line interface for DeepSignal archive tools."""

import argparse
from pathlib import Path

import yaml

from .archive import bundle, compress_closed, plan, verify


def main():
    parser = argparse.ArgumentParser(description="Compress and verify closed OpenRVDAS logs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("compress", "plan"):
        action = subparsers.add_parser(command)
        action.add_argument("root")
        action.add_argument("--codec", default="auto", choices=("auto", "zstd", "xz", "gzip"))
        action.add_argument("--level", type=int)
        action.add_argument("--min-age-s", type=float, default=3600)
        action.add_argument("--out")
        if command == "compress":
            action.add_argument("--delete-originals", action="store_true")
    check = subparsers.add_parser("verify")
    check.add_argument("directory")
    shore = subparsers.add_parser("bundle")
    shore.add_argument("spec")
    shore.add_argument("out")
    shore.add_argument("--codec", default="auto", choices=("auto", "zstd", "xz", "gzip"))
    args = parser.parse_args()
    if args.command == "compress":
        results = compress_closed(args.root, args.codec, args.level, args.min_age_s,
                                  args.delete_originals, args.out)
        for result in results:
            print(result.output)
    elif args.command == "plan":
        plan(args.root, args.codec, args.level, args.min_age_s, args.out)
    elif args.command == "verify":
        print("verified %d archive entries" % verify(args.directory))
    else:
        with Path(args.spec).open(encoding="utf-8") as stream:
            spec = yaml.safe_load(stream)
        for result in bundle(spec, args.out, args.codec):
            print(result.archive)


if __name__ == "__main__":
    main()
