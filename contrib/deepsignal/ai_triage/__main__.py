"""AI triage setup command."""
import argparse
import getpass

from contrib.deepsignal.ai_triage import setup


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
        result = setup.store_key(choices[selected]["name"].lower(), key)
        print(result.get("warning") or "Key stored securely")


if __name__ == "__main__":
    main()
