"""Command-line entry point."""

import argparse
import yaml

from contrib.deepsignal.coupling.atlas import run


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)
    atlas = subparsers.add_parser('atlas')
    atlas.add_argument('--config', required=True)
    args = parser.parse_args()
    with open(args.config, encoding='utf-8') as stream:
        config = yaml.safe_load(stream)
    result = run(config)
    print('wrote %d hypotheses; %d confirmed' %
          (len(result['hypotheses']),
           sum(h['status'] == 'confirmed' for h in result['hypotheses'])))


if __name__ == '__main__':
    main()
