# Stream discovery

Plug the instrument in, then run passive discovery from the repository root:

```sh
python3 -m contrib.deepsignal.discovery.discovery --all-serial --udp 6221-6230 \
  --files /path/to/logs --capture captures
```

The command prints a table and writes `discovery.json`. Captures contain at most 200 lines per
stream and are suitable for the onboarding wizard:

```sh
python3 -m contrib.deepsignal.onboard
```

Serial discovery tries common baud rates but **never sends a byte**. A polled instrument can
therefore appear silent. Scanning a port used by a running logger is skipped by design; stop the
logger first only if shipboard operating procedures permit it. UDP listening is local only. MQTT,
Redis, CDS, TCP, and HTTP are contacted only when an operator explicitly supplies a target. MQTT
credentials are read from the path supplied with `--mqtt-credentials` and are never displayed.

Use `--help` for all options. Serial ports report printable-data quality, NMEA talker and sentence
identifiers, and the best baud rate. UDP and other live sources report line rate and samples. Files
must have been modified in the last hour; older files are omitted rather than presented as live.
Pass a cruise definition such as `--config contrib/deepsignal/configs/discovery_example.yaml` to add
its `udp_ports` list to explicit `--udp` values. YAML is loaded safely and is never executed.

This tool is observational, not a lock-stealing probe. A lead must still run the real-hardware check
outside the development sandbox before relying on it during a cruise.
