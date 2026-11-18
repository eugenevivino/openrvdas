"""Command-line interface for the inventory cruise generator."""

import argparse
import difflib
import os
import sys
from datetime import datetime, timezone

from . import file_sha256, generate, render


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("acquisition")
    parser.add_argument("--history")
    parser.add_argument("--diff")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        definition = generate(args.acquisition, args.history)
        paths = [args.acquisition] + ([args.history] if args.history else [])
        provenance = {path: file_sha256(path) for path in paths}
        modified = max(os.path.getmtime(path) for path in paths)
        provenance["generated_at"] = datetime.fromtimestamp(
            modified, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        output = render(definition, provenance)
        if args.diff:
            with open(args.diff, encoding="utf-8") as current:
                sys.stdout.writelines(difflib.unified_diff(
                    current.readlines(), output.splitlines(keepends=True),
                    fromfile=args.diff, tofile=args.out or "generated"))
        if args.out:
            try:
                with open(args.out, "x", encoding="utf-8") as destination:
                    destination.write(output)
            except FileExistsError:
                parser.error(f"output file '{args.out}' already exists")
        elif not args.diff:
            sys.stdout.write(output)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    main()
