"""AI triage setup command."""
import argparse
import getpass

from contrib.deepsignal.ai_triage import setup
from contrib.deepsignal.ai_triage.vault import VaultUnavailable


def main():
    parser = argparse.ArgumentParser(description="Configure DeepSignal AI triage")
    parser.add_argument("command", choices=["setup"])
    args = parser.parse_args()
    if args.command == "setup":
        choices = setup.providers()
        for number, choice in enumerate(choices, 1):
            print("%d. %s (%s)" % (number, choice["name"], choice["url"]))
        selected = int(input("Provider number: ")) - 1
        key = getpass.getpass("API key: ")
        try:
            result = setup.store_key(choices[selected]["name"].lower(), key)
            print(result["message"])
        except VaultUnavailable as error:
            print(error)


if __name__ == "__main__":
    main()
