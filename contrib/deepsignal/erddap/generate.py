"""Generate and validate ERDDAP ``EDDTableFromAsciiFiles`` configuration."""

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path


DATASET_ID = re.compile(r"^[A-Za-z0-9_]+$")
FLAG_VALUES = "1 2 3 4 9"
FLAG_MEANINGS = "pass not_evaluated suspect fail missing"
ATTRIBUTE_NAMES = ("units", "long_name", "standard_name", "ioos_category")


def _element(parent, tag, text=None, **attributes):
    element = ET.SubElement(parent, tag, attributes)
    if text is not None:
        element.text = str(text)
    return element


def _attribute(parent, name, value):
    _element(parent, "att", value, name=name)


def _data_variable(dataset_element, column, attributes, data_type="double"):
    variable = _element(dataset_element, "dataVariable")
    _element(variable, "sourceName", column)
    _element(variable, "destinationName", column)
    _element(variable, "dataType", data_type)
    add_attributes = _element(variable, "addAttributes")
    for name, value in attributes:
        _attribute(add_attributes, name, value)


def generate(config):
    """Return an XML fragment containing each configured ERDDAP dataset."""
    fragments = []
    for dataset in config.get("datasets", []):
        root = ET.Element("dataset", {
            "type": "EDDTableFromAsciiFiles",
            "datasetID": str(dataset["id"]),
            "active": "true",
        })
        _element(root, "reloadEveryNMinutes", dataset["reload_minutes"])
        directory = str(dataset["directory"])
        _element(root, "fileDir", directory if directory.endswith(os.sep) else directory + os.sep)
        _element(root, "fileNameRegex", dataset["file_regex"])

        add_attributes = _element(root, "addAttributes")
        globals_ = (
            ("cdm_data_type", "Other"),
            ("Conventions", "COARDS, CF-1.10, ACDD-1.3"),
            ("institution", config["institution"]),
            ("title", dataset["title"]),
            ("summary", config["summary"]),
            ("platform", "ship"),
            ("infoUrl", config["infoUrl"]),
            ("license", config.get("license", "See ship data policy")),
        )
        for name, value in globals_:
            _attribute(add_attributes, name, value)

        time_column = dataset["time_column"]
        _data_variable(root, time_column,
                       (("units", "yyyy-MM-dd'T'HH:mm:ssZ"),), data_type="String")
        for variable in dataset.get("variables", []):
            if variable["column"] == time_column:
                continue
            attributes = [(name, variable[name]) for name in ATTRIBUTE_NAMES if name in variable]
            if "flag_of" in variable:
                attributes.extend((
                    ("flag_values", FLAG_VALUES),
                    ("flag_meanings", FLAG_MEANINGS),
                ))
            _data_variable(root, variable["column"], attributes)
        ET.indent(root, space="  ")
        fragments.append(ET.tostring(root, encoding="unicode", short_empty_elements=False))
    return "\n".join(fragments) + ("\n" if fragments else "")


def _read_cf_names():
    """Read an optional #117 CF vocabulary file, returning None when absent."""
    vocab_dir = Path(__file__).resolve().parents[1] / "vocab"
    candidates = ("cf_standard_names.txt", "cf_standard_names.yaml", "cf_standard_names.yml")
    for name in candidates:
        path = vocab_dir / name
        if not path.is_file():
            continue
        if path.suffix == ".txt":
            return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")}
        import yaml
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(content, dict):
            content = content.get("standard_names", content.keys())
        return set(content or [])
    return None


def check(config):
    """Return plain-English error and warning lines for a configuration mapping."""
    findings = []
    seen_ids = set()
    cf_names = config.get("cf_standard_names")
    if cf_names is None:
        cf_names = _read_cf_names()
    if cf_names is not None:
        cf_names = set(cf_names)

    for dataset in config.get("datasets", []):
        dataset_id = dataset.get("id")
        if not isinstance(dataset_id, str) or not DATASET_ID.fullmatch(dataset_id):
            findings.append(
                f"ERROR: dataset id saw {dataset_id!r}; expected letters, digits, or underscore, "
                "for example revelle_met_1min")
        if dataset_id in seen_ids:
            findings.append(
                f"ERROR: dataset id saw duplicate {dataset_id!r}; expected a unique id, "
                "for example revelle_met_1min")
        seen_ids.add(dataset_id)
        variables = dataset.get("variables", [])
        columns = {variable.get("column") for variable in variables}
        for variable in variables:
            column = variable.get("column", "<missing column>")
            if "units" not in variable or variable["units"] in (None, ""):
                findings.append(
                    f"ERROR: variable {column} units saw missing; expected a units value, "
                    "for example degree_C")
            flag_of = variable.get("flag_of")
            if flag_of is not None and flag_of not in columns:
                findings.append(
                    f"ERROR: variable {column} flag_of saw {flag_of!r}; expected an existing "
                    "column, for example air_temperature")
            standard_name = variable.get("standard_name")
            if cf_names is not None and standard_name and standard_name not in cf_names:
                findings.append(
                    f"WARNING: variable {column} standard_name saw {standard_name!r}; expected "
                    "a name in the installed CF vocabulary, for example air_temperature")
    return findings
