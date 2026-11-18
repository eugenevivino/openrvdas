"""Command-line interface for correction ledger events."""

import argparse
from datetime import datetime, timezone
from uuid import uuid4

from .ledger import Ledger, _METHOD_FIELDS


def _cli_number(value):
    try:
        return int(value, 10)
    except ValueError:
        return float(value)


def _display(text):
    return ''.join(char if char.isprintable() else repr(char)[1:-1] for char in text)


def _parser():
    parser = argparse.ArgumentParser(description='Propose and review sensor data corrections.')
    commands = parser.add_subparsers(dest='event', required=True)
    for name in ('propose', 'approve', 'reject', 'rollback', 'list', 'verify'):
        command = commands.add_parser(name)
        command.add_argument('--ledger', required=True, help='Path to the JSON Lines ledger')
        if name == 'propose':
            for key in ('author', 'field', 'start', 'end', 'reason', 'code-version',
                        'correction-state', 'model-id'):
                command.add_argument(f'--{key}', required=True)
            command.add_argument('--method', choices=_METHOD_FIELDS, required=True)
            command.add_argument('--instrument')
            command.add_argument('--standard-uncertainty', type=_cli_number, required=True)
            command.add_argument('--coverage-interval', type=_cli_number, nargs=2)
            command.add_argument('--independence-score', type=_cli_number)
            command.add_argument('--evidence', nargs='+', required=True)
            command.add_argument('--fit-refs', nargs='*', required=True)
            command.add_argument('--validation-refs', nargs='*', required=True)
            for parameter in ('value', 'rate-per-day', 'seconds', 'offset', 'gain'):
                command.add_argument(f'--{parameter}', type=_cli_number)
            command.add_argument('--t0')
            command.add_argument('--coefficients', nargs='+', type=_cli_number)
        elif name in ('approve', 'reject', 'rollback'):
            command.add_argument('id', help='Proposal UUID')
            command.add_argument('--by', required=True)
            command.add_argument('--reason', required=True)
    return parser


def main():
    parser = _parser()
    event = {key: value for key, value in vars(parser.parse_args()).items() if value is not None}
    path = event.pop('ledger')
    action = event['event']
    try:
        if action in ('list', 'verify'):
            ledger = Ledger.load(path)
            if action == 'verify':
                print(f'Ledger verified: {_display(path)}')
            else:
                for entry in ledger.entries.values():
                    status = entry['status'].replace('_', ' ')
                    print(f'{entry["id"]} is {status}: {entry["method"]} '
                          f'for {_display(entry["field"])} '
                          f'from {entry["start"]} to {entry["end"]}, proposed by '
                          f'{_display(entry["author"])}. Reason: {_display(entry["reason"])}')
            return
        if action == 'propose':
            event['id'] = str(uuid4())
        else:
            event['time'] = datetime.now(timezone.utc).isoformat()
        Ledger.append(path, event)
        print(event['id'])
    except (OSError, ValueError) as error:
        parser.exit(1, f'{_display(str(error))}\n')


if __name__ == '__main__':
    main()
