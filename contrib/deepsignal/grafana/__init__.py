"""Generate deterministic Grafana quality dashboards from cruise definitions."""

import json
from pathlib import Path

import yaml


QC_MAPPINGS = [
    {"options": {"color": "green", "text": "good"}, "value": 1},
    {"options": {"color": "orange", "text": "suspect"}, "value": 3},
    {"options": {"color": "red", "text": "fail"}, "value": 4},
    {"options": {"color": "gray", "text": "missing"}, "value": 9},
]
QC_THRESHOLDS = [
    {"color": "green", "value": 1},
    {"color": "orange", "value": 3},
    {"color": "red", "value": 4},
    {"color": "gray", "value": 9},
]


def _option(options, name, default=None):
    if options is None:
        return default
    if isinstance(options, dict):
        return options.get(name, default)
    return getattr(options, name, default)


def _walk_modules(value):
    if isinstance(value, dict):
        if "class" in value:
            yield value
        for child in value.values():
            yield from _walk_modules(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_modules(child)


def _device_fields(definition_path, base_dir):
    path = Path(definition_path)
    if not path.is_absolute():
        path = Path(base_dir) / path
    if not path.is_file():
        return {}
    definition = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    result = {}
    for device, settings in definition.get("devices", {}).items():
        result[device] = sorted(set(settings.get("fields", {}).values()))
    return result


def _derived_fields(config):
    fields = set()
    for module in _walk_modules(config):
        kwargs = module.get("kwargs", {})
        subscription = kwargs.get("subscription", {})
        fields.update(subscription.get("fields", {}))
        configured = kwargs.get("fields", {})
        fields.update(configured if isinstance(configured, dict) else [])
        for name, value in kwargs.items():
            if name.endswith("_name") and isinstance(value, str):
                fields.add(value)
    return sorted(fields)


def _groups(cruise, options):
    configured_fields = _option(options, "fields", {})
    base_dir = _option(options, "base_dir", Path.cwd())
    definitions = {}
    for module in _walk_modules(cruise):
        if module.get("class") == "ParseTransform":
            path = module.get("kwargs", {}).get("definition_path")
            if path:
                definitions.update(_device_fields(path, base_dir))

    groups = []
    configs = cruise.get("logger_configs", cruise.get("configs", {}))
    for logger, logger_info in sorted(cruise.get("loggers", {}).items()):
        candidates = [configs.get(name, {}) for name in logger_info.get("configs", [])]
        influx = []
        for config in candidates:
            influx.extend(module for module in _walk_modules(config)
                          if module.get("class") == "InfluxDBWriter")
        if not influx:
            continue
        writer = influx[0].get("kwargs", {})
        bucket = writer.get("bucket_name")
        if not bucket:
            raise ValueError("bucket_name saw a missing value; expected a non-empty string, "
                             "for example bucket_name: openrvdas")
        measurement = writer.get("measurement_name", logger)
        fields = configured_fields.get(logger) or definitions.get(logger)
        parses_records = any(module.get("class") == "ParseTransform"
                             for config in candidates for module in _walk_modules(config))
        if not fields and parses_records:
            fields = [field for device_fields in definitions.values()
                      for field in device_fields]
        if not fields:
            fields = _derived_fields(candidates)
        fields = sorted(field for field in set(fields or []) if not field.endswith("_QC"))
        if fields:
            groups.append((logger, bucket, measurement, fields))
    return groups


def _flux(bucket, measurement, field):
    return (f'from(bucket: "{bucket}")\n'
            '  |> range(start: $__from, stop: $__to)\n'
            f'  |> filter(fn: (r) => r._measurement == "{measurement}")\n'
            f'  |> filter(fn: (r) => r._field == "{field}" or '
            f'r._field == "{field}_QC")')


def _value_panel(panel_id, logger, bucket, measurement, field):
    return {
        "fieldConfig": {"defaults": {
            "mappings": [{"options": QC_MAPPINGS, "type": "value"}],
            "thresholds": {"mode": "absolute", "steps": QC_THRESHOLDS},
        }},
        "id": panel_id,
        "targets": [{"query": _flux(bucket, measurement, field), "refId": "A"}],
        "title": field,
        "type": "timeseries",
        "description": f"{logger} value and {field}_QC quality flag",
    }


def _stale_panel(panel_id, bucket, measurement, field):
    query = (_flux(bucket, measurement, field).rsplit("\n", 1)[0]
             + f'\n  |> filter(fn: (r) => r._field == "{field}")\n'
               '  |> last()\n  |> map(fn: (r) => ({ r with _value: '
               'float(v: uint(v: now()) - uint(v: r._time)) / 1000000000.0 }))')
    return {
        "id": panel_id,
        "targets": [{"query": query, "refId": "A"}],
        "title": f"{field} seconds since last value",
        "type": "stat",
    }


def generate(cruise, options=None):
    """Return one schema version 39 dashboard containing all logger groups."""
    if not isinstance(cruise, dict):
        raise ValueError("cruise saw a non-mapping value; expected a mapping, "
                         "for example cruise: {}")
    panels = []
    panel_id = 1
    compass = []
    for logger, bucket, measurement, fields in _groups(cruise, options):
        for field in fields:
            panels.append(_value_panel(panel_id, logger, bucket, measurement, field))
            panels.append(_stale_panel(panel_id + 1, bucket, measurement, field))
            panel_id += 2
        headings = [field for field in fields if "heading" in field.lower()]
        winds = [field for field in fields if "wind" in field.lower()]
        if headings and winds:
            compass.append({
                "id": panel_id,
                "optional": True,
                "pluginVersion": "optional",
                "title": f"{logger} heading and wind",
                "type": "oceandatatools-compass-panel",
                "targets": [{"query": _flux(bucket, measurement, field), "refId": chr(65 + i)}
                            for i, field in enumerate(headings[:1] + winds)],
            })
            panel_id += 1
    panels.extend(compass)
    cruise_id = cruise.get("cruise", {}).get("id", "OpenRVDAS")
    return {
        "panels": panels,
        "schemaVersion": 39,
        "tags": ["OpenRVDAS", "quality"],
        "title": f"{cruise_id} data quality",
        "uid": f"openrvdas-{str(cruise_id).lower()}-quality",
    }


def alerts(cruise, options=None):
    """Return flag-failure and freshness alert rules for every generated field."""
    stale_after = _option(options, "stale_after_s", 300)
    if not isinstance(stale_after, (int, float)) or stale_after <= 0:
        raise ValueError("stale_after_s saw an invalid value; expected a positive number, "
                         "for example stale_after_s: 300")
    rules = []
    for logger, bucket, measurement, fields in _groups(cruise, options):
        for field in fields:
            common = {"bucket": bucket, "field": field, "logger": logger,
                      "measurement": measurement}
            rules.append({**common, "condition": f"{field}_QC == 4", "for": "5m",
                          "kind": "fail", "name": f"{logger}.{field}.failed"})
            rules.append({**common, "kind": "stale", "name": f"{logger}.{field}.stale",
                          "stale_after_s": stale_after})
    return rules


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build(cruise, output_dir, options=None):
    """Write dashboard, alert, and provisioning JSON/YAML files."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    dashboard_path = output / "quality-dashboard.json"
    alert_path = output / "quality-alerts.json"
    provider_path = output / "dashboards.yaml"
    dashboard_path.write_bytes(_json_bytes(generate(cruise, options)))
    alert_path.write_bytes(_json_bytes(alerts(cruise, options)))
    provider = {"apiVersion": 1, "providers": [{
        "disableDeletion": False,
        "name": "OpenRVDAS quality",
        "options": {"path": "/var/lib/grafana/dashboards/openrvdas"},
        "orgId": 1,
        "type": "file",
        "updateIntervalSeconds": 30,
    }]}
    provider_path.write_text(yaml.safe_dump(provider, sort_keys=True), encoding="utf-8")
    return [dashboard_path, alert_path, provider_path]
