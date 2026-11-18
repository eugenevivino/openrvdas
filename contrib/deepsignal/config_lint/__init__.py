"""Ship-sense checks for OpenRVDAS cruise definitions."""

from pathlib import Path


LEVELS = {"error", "warning", "info"}


def _finding(level, where, message, fix):
    return {"level": level, "where": where, "message": message, "fix": fix}


def _core_findings(cruise_dict):
    """Run the core structural validator when this core version provides one."""
    try:
        from logger.utils.validate_config import validate_config
    except (ImportError, ModuleNotFoundError):
        return []

    try:
        results = validate_config(cruise_dict)
    except (TypeError, ValueError, KeyError) as error:
        return [_finding("error", "cruise", "Core schema validation failed: %s" % error,
                         "Correct the named structure or value, then run the linter again.")]

    findings = []
    for result in results or []:
        if isinstance(result, dict):
            level = result.get("level", "error")
            findings.append(_finding(
                level if level in LEVELS else "error",
                result.get("where", "cruise"),
                result.get("message", str(result)),
                result.get("fix", "Correct the core schema finding."),
            ))
        else:
            findings.append(_finding("error", "cruise", "Core schema validation: %s" % result,
                                     "Correct the core schema finding."))
    return findings


def _components(config):
    """Yield top-level and composed reader/transform/writer definitions."""
    pending = []
    if isinstance(config, dict):
        for group in ("readers", "transforms", "writers"):
            value = config.get(group, [])
            if isinstance(value, list):
                pending.extend(value)
    while pending:
        item = pending.pop(0)
        if not isinstance(item, dict):
            continue
        yield item
        kwargs = item.get("kwargs", {})
        if isinstance(kwargs, dict):
            for group in ("readers", "transforms", "writers"):
                nested = kwargs.get(group, [])
                if isinstance(nested, list):
                    pending.extend(nested)


def _class_components(config, class_name):
    return [item for item in _components(config) if item.get("class") == class_name]


def _is_non_off(config):
    return isinstance(config, dict) and bool(config)


def _inside_root(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (TypeError, ValueError):
        return False


def lint(cruise_dict, root=None):
    """Return schema and ship-sense findings for *cruise_dict*."""
    findings = list(_core_findings(cruise_dict))
    if not isinstance(cruise_dict, dict):
        findings.append(_finding("error", "cruise", "Cruise YAML is not a mapping.",
                                 "Start the file with mappings such as 'cruise:' and 'loggers:'."))
        return findings

    configs = cruise_dict.get("configs", {})
    loggers = cruise_dict.get("loggers", {})
    modes = cruise_dict.get("modes", {})
    configs = configs if isinstance(configs, dict) else {}
    loggers = loggers if isinstance(loggers, dict) else {}
    modes = modes if isinstance(modes, dict) else {}
    used = set()

    for mode_name, selections in modes.items():
        selections = selections if isinstance(selections, dict) else {}
        for logger_name in loggers:
            if logger_name not in selections:
                findings.append(_finding(
                    "error", "modes.%s" % mode_name,
                    "Mode %s has no config for logger %s; expected one config name."
                    % (mode_name, logger_name),
                    "Add '%s: <config-name>'; for example, '%s: %s-off'."
                    % (logger_name, logger_name, logger_name),
                ))
        for logger_name, config_name in selections.items():
            if config_name not in configs:
                findings.append(_finding(
                    "error", "modes.%s.%s" % (mode_name, logger_name),
                    "Mode %s names config %s for logger %s, but that config does not exist."
                    % (mode_name, config_name, logger_name),
                    "Define configs.%s or select an existing config, for example '%s: %s-off'."
                    % (config_name, logger_name, logger_name),
                ))
            else:
                used.add(config_name)

        resources = {}
        for logger_name, config_name in selections.items():
            config = configs.get(config_name, {})
            for reader in _class_components(config, "SerialReader"):
                port = reader.get("kwargs", {}).get("port")
                if port is not None:
                    resources.setdefault(("serial", port), []).append((logger_name, config_name))
            for reader in _class_components(config, "UDPReader"):
                port = reader.get("kwargs", {}).get("port")
                if port is not None:
                    resources.setdefault(("UDP", port), []).append((logger_name, config_name))
        for (kind, port), owners in resources.items():
            if len(owners) > 1:
                labels = ", ".join("%s (%s)" % owner for owner in owners)
                findings.append(_finding(
                    "error", "modes.%s" % mode_name,
                    "Mode %s has %s configs reading the same %s port %s: %s."
                    % (mode_name, len(owners), kind, port, labels),
                    "Assign one reader per port; for example, keep the port only on %s."
                    % owners[0][1],
                ))

    for config_name, config in configs.items():
        where = "configs.%s" % config_name
        if config_name not in used:
            findings.append(_finding(
                "info", where, "Config %s is defined but no mode uses it." % config_name,
                "Select it in a mode or remove it; for example, 'science: {logger: %s}'."
                % config_name,
            ))
        if not _is_non_off(config):
            continue
        if not _class_components(config, "CachedDataWriter"):
            findings.append(_finding(
                "warning", where,
                "Config %s has no CachedDataWriter, so its data does not reach displays."
                % config_name,
                "Add a CachedDataWriter, for example with data_server: localhost:8766.",
            ))
        logging_modes = [name for name, selections in modes.items()
                         if ("log" in str(name).lower() or "write" in str(name).lower())
                         and isinstance(selections, dict)
                         and config_name in selections.values()]
        if logging_modes and not _class_components(config, "LogfileWriter"):
            findings.append(_finding(
                "warning", where,
                "Config %s is active in log/write mode(s) %s but has no LogfileWriter."
                % (config_name, ", ".join(map(str, logging_modes))),
                "Add a LogfileWriter with filebase under the cruise logging root.",
            ))
        for reader in _class_components(config, "SerialReader"):
            kwargs = reader.get("kwargs", {})
            if "timeout" not in kwargs:
                findings.append(_finding(
                    "warning", where,
                    "SerialReader in config %s has no timeout; a silent instrument can block it."
                    % config_name,
                    "Set a finite timeout, for example 'timeout: 1'.",
                ))
        if root is not None:
            for writer in _class_components(config, "LogfileWriter"):
                kwargs = writer.get("kwargs", {})
                path = kwargs.get("filebase", kwargs.get("path"))
                if path is not None and not _inside_root(path, root):
                    findings.append(_finding(
                        "warning", where,
                        "LogfileWriter path %s in config %s is outside configured root %s."
                        % (path, config_name, root),
                        "Move it below the root; for example, '%s/%s/raw'."
                        % (str(root).rstrip("/"), config_name),
                    ))

    prefixes = {}
    for config_name, config in configs.items():
        for transform in _class_components(config, "PrefixTransform"):
            prefix = transform.get("kwargs", {}).get("prefix")
            if prefix is not None:
                prefixes.setdefault(prefix, set()).add(config_name)
    for prefix, owners in prefixes.items():
        logger_owners = set()
        for logger_name, logger in loggers.items():
            declared = logger.get("configs", []) if isinstance(logger, dict) else []
            if any(owner in declared for owner in owners):
                logger_owners.add(logger_name)
        if len(logger_owners) > 1:
            findings.append(_finding(
                "warning", "loggers.%s" % ",".join(sorted(logger_owners)),
                "Loggers %s use the same data id %s; displays cannot distinguish their data."
                % (", ".join(sorted(logger_owners)), prefix),
                "Give each logger a unique PrefixTransform prefix, for example '%s_2'." % prefix,
            ))
    return findings


__all__ = ["lint"]
