"""Offline import and lookup tools for archive vocabulary terms."""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import xml.etree.ElementTree as ElementTree

import yaml

DEFAULT_STORE = Path(__file__).parent
NVS_IMPORT_SCHEMES = {"l22", "l35", "el1", "el2", "c17"}
CF_COMPATIBLE_UNITS = {frozenset(("K", "degree_C"))}


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_xml_root(path):
    raw = Path(path).read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("XML setting contains a DOCTYPE or ENTITY; expected entity-free XML")
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise ValueError(
            f"XML setting could not be parsed: saw {error}; expected valid XML"
        ) from error


class VocabStore:
    """A directory of imported, normalized JSON vocabulary files."""

    def __init__(self, directory=DEFAULT_STORE):
        self.directory = Path(directory)

    def _path(self, scheme):
        return self.directory / f"{scheme.lower()}.json"

    def write(self, scheme, document):
        self.directory.mkdir(parents=True, exist_ok=True)
        output = self._path(scheme)
        output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output

    def load(self, scheme):
        path = self._path(scheme)
        if not path.is_file():
            raise FileNotFoundError(
                f"scheme setting saw {scheme!r}; expected an imported vocabulary"
            )
        return json.loads(path.read_text(encoding="utf-8"))

    def lookup(self, scheme, term_id):
        return self.load(scheme).get("terms", {}).get(str(term_id))

    def search(self, scheme, text):
        needle = text.casefold()
        matches = []
        for term_id, term in self.load(scheme).get("terms", {}).items():
            haystack = " ".join(str(value) for value in term.values()).casefold()
            if needle in term_id.casefold() or needle in haystack:
                matches.append({"id": term_id, **term})
        return sorted(matches, key=lambda item: item["id"])

    def check_tags(self, yaml_path):
        tags = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
        if not isinstance(tags, dict):
            raise ValueError(
                f"tags setting saw {type(tags).__name__}; expected a mapping, "
                "for example TSG_Temp: {cf: sea_water_temperature}"
            )
        findings = []
        for local_name, tag in tags.items():
            if not isinstance(tag, dict):
                raise ValueError(
                    f"tag {local_name} setting saw {type(tag).__name__}; expected a mapping, "
                    "for example {cf: sea_water_temperature}"
                )
            units = tag.get("units")
            for scheme, term_id in tag.items():
                if scheme == "units":
                    continue
                try:
                    term = self.lookup(scheme, term_id)
                except FileNotFoundError:
                    command = "import_nvs" if scheme.lower() in NVS_IMPORT_SCHEMES else "import_csv"
                    findings.append(
                        {
                            "level": "warning",
                            "name": local_name,
                            "message": f"scheme {scheme} is not imported; import it with {command}",
                        }
                    )
                    continue
                if term is None:
                    findings.append(
                        {
                            "level": "error",
                            "name": local_name,
                            "message": f"term {term_id} is unknown in scheme {scheme}",
                        }
                    )
                    continue
                canonical = term.get("units") if scheme.lower() == "cf" else None
                if canonical and units and units != canonical:
                    if frozenset((units, canonical)) in CF_COMPATIBLE_UNITS:
                        findings.append(
                            {
                                "level": "note",
                                "name": local_name,
                                "message": (
                                    f"units {units} are compatible with CF canonical "
                                    f"units {canonical}"
                                ),
                            }
                        )
                    else:
                        findings.append(
                            {
                                "level": "error",
                                "name": local_name,
                                "message": (
                                    f"units setting saw {units}; expected {canonical}, "
                                    f"for example {canonical}"
                                ),
                            }
                        )
        return findings


def _document(scheme, version, source, terms):
    return {
        "scheme": scheme,
        "version": version,
        "source": str(source),
        "imported": _utc_now(),
        "terms": terms,
    }


def import_cf(source, store=None):
    store = store or VocabStore()
    root = _safe_xml_root(source)
    terms = {}
    for entry in root.findall(".//entry"):
        term_id = entry.get("id")
        if not term_id:
            raise ValueError(
                "CF entry id setting saw no value; expected an identifier, "
                "for example sea_water_temperature"
            )
        terms[term_id] = {
            "label": term_id.replace("_", " "),
            "units": (entry.findtext("canonical_units") or "").strip(),
            "definition": (entry.findtext("description") or "").strip(),
        }
    version = root.get("version_number") or root.get("version") or "unspecified"
    return store.write("cf", _document("cf_standard_names", version, source, terms))


def import_nvs(source, scheme, store=None):
    scheme = scheme.lower()
    if scheme not in NVS_IMPORT_SCHEMES:
        expected = ", ".join(sorted(NVS_IMPORT_SCHEMES))
        raise ValueError(
            f"scheme setting saw {scheme!r}; expected one of {expected}, for example l22"
        )
    store = store or VocabStore()
    root = _safe_xml_root(source)
    namespaces = {
        "skos": "http://www.w3.org/2004/02/skos/core#",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    terms = {}
    for concept in root.findall(".//skos:Concept", namespaces):
        notation = concept.findtext("skos:notation", namespaces=namespaces)
        identifier = concept.findtext("dc:identifier", namespaces=namespaces)
        term_id = (notation or identifier or "").strip()
        if not term_id:
            raise ValueError(
                "NVS concept identifier setting saw no value; expected "
                "skos:notation or dc:identifier"
            )
        terms[term_id] = {
            "label": (concept.findtext("skos:prefLabel", namespaces=namespaces) or "").strip(),
            "units": "",
            "definition": (
                concept.findtext("skos:definition", namespaces=namespaces) or ""
            ).strip(),
        }
    return store.write(scheme, _document(scheme, "unspecified", source, terms))


def import_csv(source, scheme, id_col, label_col, store=None):
    store = store or VocabStore()
    terms = {}
    with Path(source).open(encoding="utf-8-sig", newline="") as source_file:
        reader = csv.DictReader(source_file)
        missing = [
            column for column in (id_col, label_col) if column not in (reader.fieldnames or [])
        ]
        if missing:
            raise ValueError(
                f"CSV column setting saw missing {', '.join(missing)}; expected --id-col "
                "and --label-col names, for example code and name"
            )
        for row in reader:
            term_id = row[id_col].strip()
            if term_id:
                terms[term_id] = {"label": row[label_col].strip(), "units": "", "definition": ""}
    return store.write(scheme, _document(scheme, "unspecified", source, terms))


def lookup(scheme, term_id):
    return VocabStore().lookup(scheme, term_id)


def search(scheme, text):
    return VocabStore().search(scheme, text)


def check_tags(yaml_path):
    return VocabStore().check_tags(yaml_path)
