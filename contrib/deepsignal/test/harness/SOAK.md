# DeepSignal console soak test

The soak runner starts the real fixture, opens the requested number of console
style clients, and adds one client that reconnects every ten minutes. Each
connection requests every available field with 300 seconds of history before
continuing with live updates.

Run the Linux gate for 24 hours:

```sh
python3 -m contrib.deepsignal.test.harness.soak \
  --hours 24 --warmup-min 30 --sample-s 60 --clients 3 \
  --report soak.json
```

For a short operational check, use:

```sh
python3 -m contrib.deepsignal.test.harness.soak \
  --hours 0.05 --warmup-min 0.5 --sample-s 5 --report soak.json
```

The report contains the configuration, every sample, process and client
summaries, a verdict, and plain-language failure reasons. A run fails when it
has no post-warm-up measurements, a client receives zero new records, or any
expected process dies or lacks an RSS measurement. It also fails when median
RSS grows by more than 5 percent between the first and last ten post-warm-up
samples, or a client's median sampled maximum receive lag exceeds five seconds.
The expected processes are the cache, the manager, and all four fixture loggers.
Exit statuses are 0 for PASS, 1 for FAIL, and 2 when the fixture could not run.

The fixture dates its replay records from startup. Receive lag is the wall
clock time at receipt minus the record timestamp. Each client remembers the
latest timestamp it has seen per field, so reconnect history counts only when
it contains new records. The first new record after reconnect contributes its
full lag.
