# Cruise configuration linter

The DeepSignal configuration linter supplements OpenRVDAS's structural validator with checks that
need shipboard context. It does not load the cruise definition or contact instruments. Run it before
selecting a mode:

```sh
python -m contrib.deepsignal.config_lint cruise.yaml --root /data
```

Every output line gives a severity, the affected setting, a plain-English observation, and a concrete
fix. The command exits `1` when it finds an error, `0` when it finds only warnings or information, and
`2` when the file cannot be safely read. YAML is read with `yaml.safe_load`.

## Findings

| Level | Finding | Why it matters | Fix |
| --- | --- | --- | --- |
| error | Two active configs read one serial port. | The readers race and split or corrupt an instrument stream. | Leave one reader on the port and distribute its records through a writer. |
| error | Two active configs bind one UDP port. | One reader may fail to bind or packets may reach the wrong logger. | Give each reader a unique port, or use one reader to distribute records. |
| error | A mode names an undefined config. | The logger cannot be started in that mode. | Define the named config or select a name from `configs`. |
| error | A mode omits a logger. | Mode selection leaves that logger's state ambiguous. | Select a config, including an explicit empty `logger-off` config. |
| warning | A non-empty config has no `CachedDataWriter`. | Its records do not reach cache-backed displays. | Add a `CachedDataWriter`, normally targeting `localhost:8766`. |
| warning | A config used by a mode whose name contains `log` or `write` has no `LogfileWriter`. | A mode that appears to persist data may not do so. | Add a `LogfileWriter` with a `filebase` under the cruise log root. |
| warning | Two loggers use the same `PrefixTransform` prefix (data id). | Displays and consumers cannot reliably tell their records apart. | Give each logger a unique prefix. |
| warning | A `SerialReader` has no `timeout`. | A silent or disconnected instrument can block the reader forever. | Set a finite timeout such as `timeout: 1`. |
| warning | A `LogfileWriter` path is outside `--root`. | Data may be written outside the mounted or backed-up cruise area. | Move `filebase` or `path` beneath the supplied root. |
| info | A config is selected by no mode. | It may be stale, misspelled, or unavailable to operators. | Add it to a mode or remove it. |

The linter recursively examines components inside composed writers. Empty configs are treated as
intentional off configs. The `--root` path check is lexical after absolute path normalization; it does
not create paths or resolve configuration variables.

When `logger.utils.validate_config.validate_config` exists, its schema findings are reported first.
Older contrib-era core trees without that module still receive all DeepSignal checks.
