# Logger health

The Health page shows every logger worst first, its latest output freshness and error, and a plain next step when attention is needed.

## Turn it on and configure hints

The console discovers the module automatically. To show only selected pages, include `health` in `console.yaml`:

```yaml
pages:
  - health
```

Optional ship-specific hints go in `hints.yaml` next to the built console bundle. The first matching entry wins:

```yaml
- match:
    logger: "flr*"
    stderr: "no data.*tty"
  hint: "Check the fluorometer serial cable at the rack."
```

## Check it is working

Open **Health** and confirm the cruise mode appears, every expected logger has a row, and running loggers show **● OK**. A stopped or restarting logger moves toward the top and shows a **What to try** line. An invalid ship hint file produces a visible message and retains the built-in hints.

## What it does not do

This page does not start, stop, or reconfigure loggers. **◇ Off** means the active configuration intentionally does not run that logger; it is not counted as a fault.
