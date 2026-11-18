"""Command line interface for meteorological report templates."""

import argparse

from .verify import verify


def main():
    parser = argparse.ArgumentParser(prog='python -m contrib.deepsignal.met_reports')
    parser.add_argument('command', choices=['verify'])
    parser.add_argument('template')
    parser.add_argument('sample_file')
    args = parser.parse_args()
    return verify(args.template, args.sample_file)


if __name__ == '__main__':
    raise SystemExit(main())
