# Source-loss harness

The test observes roughly 1 Hz `MwxAirTemp` data, sends `SIGKILL` to `mwx1`,
and allows two seconds for in-flight data. It checks that the field becomes
STALE within ten seconds using the console's threshold of five times the median
of the latest 20 source intervals. It also checks for `STARTING` in
`status:logger_status` within 15 seconds.

The stock LoggerManager CLI starts the configuration and status loops. The
dead logger stays configured and reports `STARTING` because the CLI leaves
the supervisor restart loop idle. The test explicitly restarts the manager
against the same cache and requires a new logger PID and fresh weather data
within 60 seconds of the kill. The browser test checks LIVE, STALE, and LIVE
around that same operator action.

The cache-loss test stops the cache, observes the websocket close, and checks
that a client can reconnect and receive data within 30 seconds after the cache
restarts on the same port.

```sh
python3.12 -m pytest -p no:cacheprovider contrib/deepsignal/test/harness/test_source_loss.py -v
```

The `lead_run` browser check uses the console distribution, Python Playwright,
and Chromium.

```sh
python3.12 -m pytest -p no:cacheprovider contrib/deepsignal/test/console/test_source_loss_browser.py -v
```
