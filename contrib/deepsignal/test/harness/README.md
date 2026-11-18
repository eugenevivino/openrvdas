# DeepSignal real-stack fixture

This fixture launches the stock CachedDataServer and LoggerManager with the
LoggerManager's headless **in-memory ServerAPI**. It replays the NBP1406
`mwx1`, `s330`, and `knud` files and runs a stock true-winds transform.

```sh
python3 -m contrib.deepsignal.test.harness.fixture up --port 0 --speed 1 --seconds 30
python3 -m contrib.deepsignal.test.harness.fixture down
```

`READY ws://127.0.0.1:PORT loggers=4 fields=N` is printed after data and
RUNNING logger status reach the real cache. Programmatic users can use
`with Fixture() as fx`, `fx.ws_url`, `fx.kill_logger(name)`,
`fx.logger_pids()`, and `fx.stop()`.

All generated configuration, scaled replay inputs, state, and logs live in a
temporary directory. `--speed` scales copied timestamps without changing the
stock `LogfileReader(use_timestamps=True)` implementation.
