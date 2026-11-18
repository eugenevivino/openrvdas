"""Checksum-backed storage for instrument documents."""

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path, PurePosixPath
import shutil

import yaml


KINDS = ("manual", "calibration_certificate", "photo", "other")


class StoreError(ValueError):
    """An error safe to show directly to a command-line user."""


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _document_path(root, value):
    path = PurePosixPath(value) if isinstance(value, str) else PurePosixPath()
    if not value or path.is_absolute() or ".." in path.parts:
        raise StoreError(
            "index setting path saw invalid path %r; expected a relative path inside the store, "
            "for example tsg1/manual.pdf" % value)
    return root.joinpath(*path.parts)


def _load_index(root):
    index_path = root / "index.yaml"
    if not index_path.exists():
        return {"documents": []}
    try:
        value = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise StoreError(
            "index setting index.yaml saw %s; expected readable YAML, for example "
            "'documents: []'" % error) from error
    if not isinstance(value, dict) or not isinstance(value.get("documents"), list):
        raise StoreError(
            "index setting documents saw %r; expected a list, for example 'documents: []'"
            % (value.get("documents") if isinstance(value, dict) else value))
    for document in value["documents"]:
        if not isinstance(document, dict):
            raise StoreError(
                "index setting document saw %r; expected a mapping, for example "
                "'{path: tsg1/manual.pdf}'" % document)
        _document_path(root, document.get("path"))
    return value


def _write_index(root, index):
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / ".index.yaml.tmp"
    temporary.write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")
    temporary.replace(root / "index.yaml")


def add(root, source, instrument, kind, cal_id=None, title=None):
    root, source = Path(root), Path(source)
    if not source.is_file():
        raise StoreError(
            "add setting file saw %r; expected a readable file, for example ./manual.pdf"
            % str(source))
    if not instrument or instrument in (".", "..") or "/" in instrument or "\\" in instrument:
        raise StoreError(
            "add setting instrument saw %r; expected one directory name, for example tsg1"
            % instrument)
    if kind not in KINDS:
        raise StoreError(
            "add setting kind saw %r; expected manual, calibration_certificate, photo, or other; "
            "for example manual" % kind)
    if kind == "calibration_certificate" and not cal_id:
        raise StoreError(
            "add setting cal-id saw no value; expected an id for a calibration certificate, "
            "for example CAL-2026-01")
    index = _load_index(root)
    sha256 = _digest(source)
    for existing in index["documents"]:
        if existing.get("sha256") == sha256:
            raise StoreError(
                "duplicate sha256 already exists at %s" % existing.get("path", "<unknown>"))
    relative = PurePosixPath(instrument, source.name)
    destination = _document_path(root, relative.as_posix())
    if destination.exists():
        raise StoreError(
            "add setting file saw %r; expected an unused destination, for example a uniquely "
            "named file" % relative.as_posix())
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    document = {
        "path": relative.as_posix(),
        "instrument": instrument,
        "kind": kind,
        "title": title or source.name,
        "added": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sha256": sha256,
        "bytes": source.stat().st_size,
    }
    if cal_id:
        document["cal_id"] = cal_id
    index["documents"].append(document)
    _write_index(root, index)


def list_documents(root, instrument=None):
    documents = _load_index(Path(root))["documents"]
    return [
        item for item in documents
        if instrument is None or item.get("instrument") == instrument
    ]


def verify(root):
    root = Path(root)
    index = _load_index(root)
    findings = []
    indexed = set()
    for document in index["documents"]:
        path_value = document["path"]
        indexed.add(path_value)
        path = _document_path(root, path_value)
        if not path.is_file():
            findings.append("missing: %s" % path_value)
        elif _digest(path) != document.get("sha256"):
            findings.append("checksum mismatch: %s" % path_value)
    if root.exists():
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            is_index = relative == "index.yaml" or relative.startswith(".index.yaml")
            if not is_index and relative not in indexed:
                findings.append("unindexed: %s" % relative)
    return findings


def crosscheck(root, history_path):
    documents = _load_index(Path(root))["documents"]
    try:
        history = yaml.safe_load(Path(history_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise StoreError(
            "crosscheck setting history saw %s; expected readable YAML, for example history.yaml"
            % error) from error
    instruments = history.get("instruments") if isinstance(history, dict) else None
    if not isinstance(instruments, list):
        raise StoreError(
            "history setting instruments saw %r; expected a list, for example 'instruments: []'"
            % instruments)
    known = set()
    events = []
    for instrument in instruments:
        if not isinstance(instrument, dict) or not isinstance(instrument.get("events", []), list):
            raise StoreError(
                "history setting instrument saw %r; expected a mapping with an events list, "
                "for example '{id: tsg1, events: []}'" % instrument)
        instrument_id = instrument.get("id")
        for event in instrument.get("events", []):
            if isinstance(event, dict) and event.get("type") == "calibration":
                key = (instrument_id, event.get("cal_id"))
                known.add(key)
                events.append((key, event.get("certificate")))
    certificates = {
        (document.get("instrument"), document.get("cal_id"))
        for document in documents if document.get("kind") == "calibration_certificate"
    }
    findings = [
        "unknown calibration: %s %s" % key for key in sorted(certificates - known)
    ]
    for key, certificate in events:
        if certificate and key not in certificates:
            findings.append("missing document: %s %s %s" % (key[0], key[1], certificate))
    return findings


def _parser():
    parser = argparse.ArgumentParser(prog="python -m contrib.deepsignal.doc_store")
    commands = parser.add_subparsers(dest="command", required=True)
    add_parser = commands.add_parser("add")
    add_parser.add_argument("root")
    add_parser.add_argument("file")
    add_parser.add_argument("--instrument", required=True)
    add_parser.add_argument("--kind", required=True)
    add_parser.add_argument("--cal-id")
    add_parser.add_argument("--title")
    list_parser = commands.add_parser("list")
    list_parser.add_argument("root")
    list_parser.add_argument("--instrument")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("root")
    crosscheck_parser = commands.add_parser("crosscheck")
    crosscheck_parser.add_argument("root")
    crosscheck_parser.add_argument("history")
    return parser


def main(arguments=None):
    options = _parser().parse_args(arguments)
    try:
        if options.command == "add":
            add(options.root, options.file, options.instrument, options.kind,
                options.cal_id, options.title)
            return 0
        if options.command == "list":
            for document in list_documents(options.root, options.instrument):
                values = dict(document)
                values.setdefault("cal_id", "-")
                print("{path}\t{instrument}\t{kind}\t{cal_id}\t{title}".format(**values))
            return 0
        findings = (verify(options.root) if options.command == "verify" else
                    crosscheck(options.root, options.history))
        for finding in findings:
            print(finding)
        return 1 if findings else 0
    except StoreError as error:
        print(error)
        return 1
