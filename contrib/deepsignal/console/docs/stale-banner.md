# Stale banner

The stale banner tells the watch when a sensor stops reporting or its logger fails, grouped into one row per logger.

## Turn it on and configure it

The console discovers the module automatically. Its defaults alert after 30 seconds of `STALE` health and ignore no fields. To customize it, add this to `console.yaml`:

```yaml
modules:
  stale-banner:
    stale_grace_s: 30
    ignore:
      - "Test*"
      - "*_diagnostic"
```

Field names in `ignore` accept `*` and `?` globs. A failed logger or a `NO_DATA` field raises a Warning; a stale field past the grace period raises a Caution. Tap a row to see affected fields. Warning rows can be acknowledged and remain visible until recovery.

## See it working

Stop a configured logger or disconnect its input. The banner should name the logger or field, show how long it has been affected, and suggest the first check. Restore the input and confirm the row disappears.

This module does **not** alert on QARTOD/quality flags, make AI judgements, play audio, or repair a logger. Quality alerts belong to the quality module.
