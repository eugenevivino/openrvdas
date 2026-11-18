"""Command line interface for the component catalog."""

import argparse
import json
import sys

from .build import catalog, check_config_file, schema


def main(argv=None):
    parser = argparse.ArgumentParser(description='Inspect OpenRVDAS components')
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('build', help='print the complete catalog as JSON')
    show_parser = subparsers.add_parser('show', help='show one component')
    show_parser.add_argument('class_name')
    check_parser = subparsers.add_parser('check', help='check a YAML config')
    check_parser.add_argument('path')
    args = parser.parse_args(argv)
    if args.command == 'build':
        print(json.dumps(catalog(), indent=2, sort_keys=True))
        return 0
    if args.command == 'show':
        try:
            print(json.dumps({'class': args.class_name,
                              'schema': schema(args.class_name)},
                             indent=2, sort_keys=True))
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0
    result = check_config_file(args.path)
    if result['findings']:
        for finding in result['findings']:
            print(finding)
        return 1
    print('No component configuration errors. Checked %d components.' %
          result['checked'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
