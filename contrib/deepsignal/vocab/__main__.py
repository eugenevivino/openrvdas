"""Command line interface for offline vocabulary management."""

import argparse
import json

from . import VocabStore, import_cf, import_csv, import_nvs


def main():
    parser = argparse.ArgumentParser(description="Import and check archive vocabularies offline")
    parser.add_argument(
        "--store", default=None, help="directory holding normalized vocabulary JSON"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    cf_parser = commands.add_parser("import_cf")
    cf_parser.add_argument("source")
    nvs_parser = commands.add_parser("import_nvs")
    nvs_parser.add_argument("source")
    nvs_parser.add_argument("--scheme", required=True)
    csv_parser = commands.add_parser("import_csv")
    csv_parser.add_argument("source")
    csv_parser.add_argument("--scheme", required=True)
    csv_parser.add_argument("--id-col", required=True)
    csv_parser.add_argument("--label-col", required=True)
    check_parser = commands.add_parser("check")
    check_parser.add_argument("tags")
    search_parser = commands.add_parser("search")
    search_parser.add_argument("scheme")
    search_parser.add_argument("text")
    args = parser.parse_args()
    store = VocabStore(args.store) if args.store else VocabStore()
    if args.command == "import_cf":
        print(import_cf(args.source, store))
    elif args.command == "import_nvs":
        print(import_nvs(args.source, args.scheme, store))
    elif args.command == "import_csv":
        print(import_csv(args.source, args.scheme, args.id_col, args.label_col, store))
    elif args.command == "check":
        for finding in store.check_tags(args.tags):
            print(f"{finding['level']}: {finding['name']}: {finding['message']}")
    elif args.command == "search":
        print(json.dumps(store.search(args.scheme, args.text), indent=2))


if __name__ == "__main__":
    main()
