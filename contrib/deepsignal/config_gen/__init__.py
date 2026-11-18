"""Generate an OpenRVDAS cruise definition from an acquisition inventory."""

import difflib
import glob
import hashlib
import os
import warnings
from copy import deepcopy

import yaml


_BUILTIN_DEVICE_TYPES = {"Seapath330", "RMYoung85106"}
_CLASS_MODULES = {
    "SerialReader": "logger.readers.serial_reader",
    "UDPReader": "logger.readers.udp_reader",
    "PrefixTransform": "logger.transforms.prefix_transform",
    "ParseTransform": "logger.transforms.parse_transform",
    "CachedDataWriter": "logger.writers.cached_data_writer",
    "LogfileWriter": "logger.writers.logfile_writer",
}


def _error(setting, saw, expected, example):
    raise ValueError(
        f"Setting '{setting}' was {saw!r}; expected {expected}; for example: {example}")


def _load_yaml(value, setting):
    if not isinstance(value, (str, os.PathLike)):
        return deepcopy(value)
    try:
        with open(value, encoding="utf-8") as source:
            return yaml.safe_load(source)
    except (OSError, yaml.YAMLError) as exc:
        _error(setting, str(exc), "a readable YAML file", "/etc/openrvdas/input.yaml")


def _known_device_types():
    known = set(_BUILTIN_DEVICE_TYPES)
    paths = glob.glob("contrib/devices/*.yaml") + glob.glob("local/devices/*.yaml")
    for path in paths:
        try:
            with open(path, encoding="utf-8") as source:
                document = yaml.safe_load(source) or {}
        except (OSError, yaml.YAMLError):
            continue
        definitions = document.get("device_types", document)
        if isinstance(definitions, dict):
            known.update(name for name, value in definitions.items()
                         if isinstance(value, dict) and "format" in value)
    return known


def _component(class_name, kwargs=None):
    result = {"class": class_name, "module": _CLASS_MODULES[class_name]}
    if kwargs:
        result["kwargs"] = kwargs
    return result


def _reader(instrument):
    transport = instrument.get("transport")
    if not isinstance(transport, dict) or len(transport) != 1:
        _error(f"instruments.{instrument.get('id', '?')}.transport", transport,
               "exactly one 'serial' or 'udp' mapping",
               "transport: {udp: {port: 6224}}")
    kind, kwargs = next(iter(transport.items()))
    classes = {"serial": "SerialReader", "udp": "UDPReader"}
    if kind not in classes or not isinstance(kwargs, dict):
        _error(f"instruments.{instrument.get('id', '?')}.transport", transport,
               "exactly one 'serial' or 'udp' mapping",
               "transport: {serial: {port: /dev/ttyS0, baudrate: 9600}}")
    return _component(classes[kind], deepcopy(kwargs))


def _is_installed(entry):
    if "installed" in entry:
        return entry["installed"] is True
    if "end" in entry:
        return entry["end"] in (None, "")
    if "removed" in entry:
        return entry["removed"] in (None, "")
    return True


def _history_warnings(acquisition, history):
    document = _load_yaml(history, "history") or {}
    entries = document.get("instruments", document.get("history", []))
    if isinstance(entries, dict):
        entries = [dict(value, id=key) for key, value in entries.items()]
    if not isinstance(entries, list):
        _error("history.instruments", entries, "a list of instrument mappings",
               "instruments: [{id: s330, installed: true}]")
    installed = {entry.get("id") for entry in entries
                 if isinstance(entry, dict) and _is_installed(entry)}
    acquired = {item["id"] for item in acquisition["instruments"]}
    enabled = {item["id"] for item in acquisition["instruments"]
               if item.get("enabled", True)}
    for instrument_id in sorted(enabled - installed):
        warnings.warn(f"Enabled instrument '{instrument_id}' is not installed today.")
    for instrument_id in sorted(installed - acquired):
        warnings.warn(f"Installed instrument '{instrument_id}' has no acquisition entry.")


def generate(acq, history=None):
    """Return a cruise definition without modifying either input."""
    acquisition = _load_yaml(acq, "acquisition")
    if not isinstance(acquisition, dict):
        _error("acquisition", acquisition, "a YAML mapping", "cruise: {id: RR2205}")
    instruments = acquisition.get("instruments")
    if not isinstance(instruments, list):
        _error("instruments", instruments, "a list", "instruments: [{id: s330, ...}]")
    defaults = acquisition.get("defaults", {})
    modes = acquisition.get("modes", ["off", "monitor", "log"])
    # PyYAML's YAML 1.1 resolver reads an unquoted ``off`` as False.
    modes = ["off" if mode is False else mode for mode in modes]
    if modes != ["off", "monitor", "log"]:
        _error("modes", modes, "[off, monitor, log]", "modes: [off, monitor, log]")
    known = _known_device_types()
    result = {"cruise": deepcopy(acquisition.get("cruise", {})),
              "loggers": {}, "modes": {mode: {} for mode in modes}, "configs": {}}
    seen = set()
    for index, instrument in enumerate(instruments):
        if not isinstance(instrument, dict):
            _error(f"instruments[{index}]", instrument, "a mapping", "{id: s330, ...}")
        instrument_id = instrument.get("id")
        if not isinstance(instrument_id, str) or not instrument_id:
            _error(f"instruments[{index}].id", instrument_id, "a non-empty string", "s330")
        if instrument_id in seen:
            _error(f"instruments[{index}].id", instrument_id, "a unique id", "s330")
        seen.add(instrument_id)
        device_type = instrument.get("device_type")
        if device_type not in known:
            nearest = difflib.get_close_matches(str(device_type), sorted(known), n=1)
            suggestion = nearest[0] if nearest else sorted(known)[0]
            _error(f"instruments.{instrument_id}.device_type", device_type,
                   f"a known device type (nearest: {suggestion})", suggestion)
        enabled = instrument.get("enabled", True)
        config_names = [f"{instrument_id}-off"]
        result["configs"][config_names[0]] = {}
        result["modes"]["off"][instrument_id] = config_names[0]
        if enabled:
            reader = _reader(instrument)
            transforms = [
                _component("PrefixTransform", {"prefix": instrument_id}),
                _component("ParseTransform", {"definition_path": defaults.get(
                    "device_definitions", "contrib/devices/*.yaml")}),
            ]
            cache = _component("CachedDataWriter", {"data_server": defaults.get(
                "cds", "localhost:8766")})
            net = f"{instrument_id}-net"
            log = f"{instrument_id}-net+file"
            config_names += [net, log]
            common = {"readers": [reader], "transforms": transforms}
            result["configs"][net] = deepcopy(common)
            result["configs"][net]["writers"] = [cache]
            result["configs"][log] = deepcopy(common)
            filebase = os.path.join(defaults.get("logfile_root", "/data/openrvdas"),
                                    instrument_id, "raw", instrument_id)
            result["configs"][log]["writers"] = [deepcopy(cache), _component(
                "LogfileWriter", {"filebase": filebase})]
            result["modes"]["monitor"][instrument_id] = net
            result["modes"]["log"][instrument_id] = log
        result["loggers"][instrument_id] = {"configs": config_names}
    if history is not None:
        _history_warnings(acquisition, history)
    return result


def render(definition, inputs=None):
    """Render a definition with deterministic provenance comments."""
    inputs = inputs or {}
    details = ", ".join(f"{name} sha256={digest}" for name, digest in inputs.items()
                        if name != "generated_at")
    timestamp = inputs.get("generated_at", "1970-01-01T00:00:00Z")
    header = "# Generated by contrib.deepsignal.config_gen"
    if details:
        header += f" from {details}"
    header += f" at {timestamp}\n"
    return header + yaml.safe_dump(definition, sort_keys=False)


def file_sha256(path):
    with open(path, "rb") as source:
        return hashlib.sha256(source.read()).hexdigest()
