"""Command-line interface for the DeepSignal ERDDAP generator."""

import argparse
import sys

import yaml

from contrib.deepsignal.erddap.generate import check, generate


def _load(path):
    try:
        with open(path, encoding="utf-8") as stream:
            config = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(
            f"configuration YAML saw invalid content in {path!r}; expected a readable YAML "
            "mapping, for example erddap_example.yaml") from error
    if not isinstance(config, dict):
        raise ValueError(
            f"configuration root saw {type(config).__name__}; expected a YAML mapping, "
            "for example 'datasets: []'")
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate or check ERDDAP dataset configuration")
    parser.add_argument("command", choices=("generate", "check"))
    parser.add_argument("yaml_file")
    args = parser.parse_args(argv)
    try:
        config = _load(args.yaml_file)
        findings = check(config)
        if args.command == "check":
            if findings:
                print("\n".join(findings))
            return 1 if any(line.startswith("ERROR:") for line in findings) else 0
        errors = [line for line in findings if line.startswith("ERROR:")]
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        sys.stdout.write(generate(config))
        return 0
    except (KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
