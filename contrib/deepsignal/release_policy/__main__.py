"""Command-line interface for release-policy explanations."""

import argparse

from .transform import ReleasePolicyTransform


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m contrib.deepsignal.release_policy')
    subparsers = parser.add_subparsers(dest='command', required=True)
    explain_parser = subparsers.add_parser('explain')
    explain_parser.add_argument('policy')
    explain_parser.add_argument('field')
    args = parser.parse_args(argv)
    transform = ReleasePolicyTransform(args.policy)
    print(transform.explain(args.field))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
