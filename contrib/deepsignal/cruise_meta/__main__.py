"""Command line interface for cruise metadata."""

import argparse
import sys

import yaml

from . import check as check_metadata
from . import load


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check or display cruise metadata.')
    parser.add_argument('command', choices=('check', 'show'))
    parser.add_argument('file')
    arguments = parser.parse_args(argv)
    try:
        metadata = load(arguments.file)
    except (OSError, ValueError, yaml.YAMLError) as error:
        message = ' '.join(str(error).splitlines())
        print(f'ERROR: {message}', file=sys.stderr)
        return 1
    if arguments.command == 'check':
        warnings = check_metadata(metadata)
        print(f'OK: {arguments.file}')
        for warning in warnings:
            print(f'WARNING: {warning}')
    else:
        print(yaml.safe_dump(metadata, sort_keys=False).rstrip())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
