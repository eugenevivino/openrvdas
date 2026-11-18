"""Build safe, reviewable logger proposals."""
import datetime
from pathlib import Path

import yaml


def _reader(transport):
    if set(transport) == {"serial"}:
        settings = transport["serial"]
        port = settings.get("port")
        baudrate = settings.get("baudrate")
        if not port or not isinstance(baudrate, int):
            raise ValueError(
                f"serial setting: saw {settings!r}; expected port and integer baudrate; "
                "example: {'port': '/dev/ttyUSB0', 'baudrate': 9600}"
            )
        return {"class": "SerialReader", "kwargs": {"port": port, "baudrate": baudrate}}
    if set(transport) == {"udp"}:
        port = transport["udp"].get("port")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(
                f"udp port setting: saw {port!r}; expected integer 1-65535; example: 5000"
            )
        return {"class": "UDPReader", "kwargs": {"port": port}}
    raise ValueError(
        f"transport setting: saw {transport!r}; expected serial or udp; "
        "example: {'udp': {'port': 5000}}"
    )


def propose(candidate, transport):
    """Return an OpenRVDAS logger proposal dictionary."""
    reader = _reader(transport)
    parse = []
    if candidate.score >= 0.8:
        parse = [{"class": "ParseTransform", "kwargs": {
            "field_patterns": candidate.patterns,
            "metadata": candidate.metadata,
            "record_format": "{field_string}",
        }}]
    prefix = {"class": "PrefixTransform", "kwargs": {"prefix": "onboard"}}
    cached = {"class": "CachedDataWriter"}
    logfile = {"class": "LogfileWriter", "kwargs": {
        "filebase": "/var/tmp/log/onboard/raw/onboard"
    }}
    network = {
        "readers": [reader], "transforms": parse + [prefix], "writers": [cached]
    }
    network_file = {
        "readers": [reader], "transforms": parse + [prefix],
        "writers": [cached, logfile],
    }
    return {"logger_configs": {
        "onboard-off": {}, "onboard-net": network, "onboard-net+file": network_file,
    }}


def proposal_yaml(proposal, capture, proposed_at=None):
    """Serialize a proposal with capture provenance."""
    date = proposed_at or datetime.date.today().isoformat()
    capture_name = Path(capture).resolve()
    header = (
        "# proposed by the DeepSignal onboarding wizard\n"
        f"# capture: {capture_name}\n# date: {date}\n"
    )
    return header + yaml.safe_dump(proposal, sort_keys=False)
