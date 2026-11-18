# Host health reader

`HostHealthReader` publishes acquisition computer health as an ordinary
`DASRecord` with data ID `host`. It samples configured filesystems, available
memory, one-minute load, uptime, clock offset, and recent supervisord starts.
The reader does not require a network connection.

Configure `disk_paths` as a mapping from a short field suffix to a filesystem
path. The defaults are `root: /` and `log: /var/log/openrvdas`. For example,
`root` produces `host_disk_free_pct_root` and `host_disk_free_gb_root`.
`interval` defaults to 30 seconds and `restart_window` defaults to 300 seconds.

The clock field is omitted when `chronyc` is not installed. The supervisor
field is similarly omitted when `supervisorctl` is unavailable. Any individual
probe failure omits only that probe's fields and logs the failure once.

## Suggested health-page thresholds

Warn when disk free space falls below 10 percent and alarm below 5 percent.
Warn when the absolute value of `host_clock_offset_s` exceeds 0.5 seconds.
Sites should choose memory, load, restart, and uptime thresholds based on their
hardware and operating practices.
