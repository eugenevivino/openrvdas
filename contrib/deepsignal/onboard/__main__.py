"""Command-line sensor onboarding wizard."""
import argparse
from pathlib import Path

from .diff import proposal_diff, write_proposal
from .fingerprint import identify
from .propose import propose, proposal_yaml
from .trial import run_trial


def _parser():
    parser = argparse.ArgumentParser(description="Identify a capture and propose a logger")
    parser.add_argument("capture", type=Path)
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--serial", metavar="PORT")
    transport.add_argument("--udp", type=int, metavar="PORT")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--cruise", type=Path)
    parser.add_argument("--write", type=Path)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if not args.capture.is_file():
        _parser().error(
            f"capture setting: saw missing file {args.capture}; expected a readable file; "
            "example: capture.txt"
        )
    lines = args.capture.read_text(encoding="utf-8").splitlines()
    candidate = identify(lines)[0]
    transport = ({"serial": {"port": args.serial, "baudrate": args.baud}}
                 if args.serial else {"udp": {"port": args.udp}})
    proposal = propose(candidate, transport)
    result = run_trial(args.capture, candidate) if candidate.score >= 0.8 else None
    print(candidate.evidence)
    if result:
        print(f"Trial: {result.records_parsed} records; fields: {', '.join(result.fields)}")
        if result.failed_lines:
            print("Failed lines:")
            print("\n".join(result.failed_lines))
    if args.cruise:
        print(proposal_diff(args.cruise, proposal), end="")
    elif not args.write:
        print(proposal_yaml(proposal, args.capture), end="")
    if args.write:
        try:
            write_proposal(args.write, proposal, args.capture)
        except FileExistsError as error:
            _parser().error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
