# DeepSignal real-stack fixture

This fixture launches the stock CachedDataServer and LoggerManager with the
LoggerManager's headless **in-memory ServerAPI**. The cache listens on IPv4
loopback (127.0.0.1). The fixture replays the NBP1406
`mwx1`, `s330`, and `knud` files and runs a stock true-winds transform.

```sh
python3 -m contrib.deepsignal.test.harness.fixture up --port 0 --speed 1 --seconds 30
python3 -m contrib.deepsignal.test.harness.fixture down
```

`READY ws://127.0.0.1:PORT loggers=4 fields=N` is printed after weather, GNSS,
depth, derived true wind, and logger status data reach the cache. Programmatic users can use
`with Fixture() as fx`, `fx.ws_url`, `fx.kill_logger(name)`,
`fx.logger_pids()`, and `fx.stop()`.

All generated configuration, replay inputs, state, and logs live in a temporary
directory. The first record emitted by a fixture reader establishes a shared
clock for that manager launch. `--speed` scales the archived time offsets within
and across streams. Records that run late keep their scheduled source timestamps,
so the cache and console can observe receive lag.

See [Source-loss harness](SOURCE-LOSS.md) for the manager's behavior after a
logger dies and the operator recovery check.

The fixture process applies a small compatibility shim because the stock 2024
CachedDataServer uses the legacy two-argument websocket handler signature,
which websockets 14 and newer no longer accepts. The clean long-term answer is
either a `websockets<14` pin or a CachedDataServer fix, proposed upstream only
after Eugene's approval under D-UPSTREAM0.
