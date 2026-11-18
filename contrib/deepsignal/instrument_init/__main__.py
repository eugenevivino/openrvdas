"""Command line interface for instrument initialization."""

import argparse
import json
import socket
import sys

from .api import propose_init
from .profile import ProfileError, load_profile
from .runner import AuditLog, run


class _SerialTransport:
    def __init__(self, port, baud):
        import serial
        self.connection = serial.Serial(port, baudrate=baud)

    def write(self, data):
        self.connection.write(data)

    def readline(self, timeout):
        self.connection.timeout = timeout
        return self.connection.readline() or None


class _TCPTransport:
    def __init__(self, address):
        host, port = address.rsplit(':', 1)
        self.connection = socket.create_connection((host, int(port)))
        self.file = self.connection.makefile('rb')

    def write(self, data):
        self.connection.sendall(data)

    def readline(self, timeout):
        self.connection.settimeout(timeout)
        try:
            return self.file.readline() or None
        except socket.timeout:
            return None


def _parser():
    parser = argparse.ArgumentParser(prog='python -m contrib.deepsignal.instrument_init')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('check', 'plan'):
        child = commands.add_parser(name)
        child.add_argument('profile')
    execute = commands.add_parser('run')
    execute.add_argument('profile')
    target = execute.add_mutually_exclusive_group(required=True)
    target.add_argument('--serial')
    target.add_argument('--tcp')
    execute.add_argument('--baud', type=int, default=9600)
    execute.add_argument('--audit-log', default='instrument_init_audit.jsonl')
    execute.add_argument('--allow-persist', action='store_true')
    execute.add_argument('--yes', action='store_true')
    view = commands.add_parser('log')
    view.add_argument('audit')
    view.add_argument('--instrument')
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == 'check':
            profile = load_profile(args.profile)
            print(f'valid: {profile["profile_id"]} version {profile["version"]}')
        elif args.command == 'plan':
            profile = load_profile(args.profile)
            proposal = propose_init(profile, {'type': 'unopened'})
            for step in proposal['steps']:
                print(f'{step["name"]} [{step["class"]}]: '
                      f'{step["bytes_text"]!r} hex={step["bytes_hex"]} '
                      f'expect={step["expect"]!r}')
        elif args.command == 'run':
            if not args.yes:
                _parser().error('run requires --yes')
            profile = load_profile(args.profile)
            transport = (_SerialTransport(args.serial, args.baud) if args.serial
                         else _TCPTransport(args.tcp))
            classes = {'query', 'setup', 'persist'} if args.allow_persist else {'query', 'setup'}
            result = run(profile, transport, 'manual', AuditLog(args.audit_log), classes=classes)
            print(json.dumps(result, sort_keys=True))
            return 0 if result['ok'] else 1
        else:
            with open(args.audit, encoding='utf-8') as stream:
                for line in stream:
                    record = json.loads(line)
                    if not args.instrument or record['instrument'] == args.instrument:
                        print(f'{record["utc"]} {record["instrument"]} '
                              f'{record["step"]} {record["event"]} '
                              f'{record["bytes_text"]!r} match={record["match"]}')
    except (OSError, ProfileError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
