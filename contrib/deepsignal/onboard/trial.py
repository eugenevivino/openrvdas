"""Trial a candidate against a capture without changing source data."""
from dataclasses import dataclass

from logger.readers.logfile_reader import LogfileReader
from logger.readers.text_file_reader import TextFileReader
from logger.utils.record_parser import RecordParser


@dataclass
class TrialResult:
    records_parsed: int
    fields: list[str]
    units: dict[str, str]
    failed_lines: list[str]


def run_trial(capture, candidate):
    """Read and parse a capture, reporting failures rather than hiding them."""
    with open(capture, encoding="utf-8") as stream:
        first = stream.readline()
    timestamped = "T" in first.partition(" ")[0] and first.partition(" ")[0].endswith("Z")
    reader = LogfileReader(filebase=str(capture), quiet=True) if timestamped else TextFileReader(
        file_spec=str(capture)
    )
    parser = RecordParser(
        record_format="{field_string}", field_patterns=candidate.patterns,
        metadata=candidate.metadata, quiet=True,
    )
    parsed = []
    failures = []
    while True:
        record = reader.read()
        if record is None:
            break
        payload = record.partition(" ")[2] if timestamped else record
        result = parser.parse_record(payload.strip())
        if result is None:
            if len(failures) < 5:
                failures.append(record.rstrip())
        else:
            parsed.append(result)
    storage_reader = getattr(reader, "reader", reader)
    if storage_reader.current_file:
        storage_reader.current_file.close()
    fields = sorted({key for result in parsed for key in result.get("fields", {})})
    units = {name: details.get("units", "") for name, details in candidate.metadata.items()
             if name in fields}
    return TrialResult(len(parsed), fields, units, failures)
