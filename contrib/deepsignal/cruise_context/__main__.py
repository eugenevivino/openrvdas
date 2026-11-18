"""Command line interface for cruise context import."""
import argparse
import difflib
import os

import yaml

from . import fetch, from_openvdm


def main(argv=None):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    pull = commands.add_parser("pull")
    pull.add_argument("--openvdm", required=True)
    pull.add_argument("--out", default="cruise.yaml")
    pull.add_argument("--diff")
    args = parser.parse_args(argv)
    rendered = yaml.safe_dump(from_openvdm(fetch("openvdm", args.openvdm)), sort_keys=False)
    if args.diff:
        with open(args.diff, encoding="utf-8") as stream:
            old = stream.read()
        print("".join(difflib.unified_diff(old.splitlines(True), rendered.splitlines(True),
                                           fromfile=args.diff, tofile="OpenVDM")), end="")
        return 0
    if os.path.exists(args.out):
        raise FileExistsError("refusing to overwrite existing output %s" % args.out)
    with open(args.out, "x", encoding="utf-8") as stream:
        stream.write(rendered)
    return 0


if __name__ == "__main__":
    main()
