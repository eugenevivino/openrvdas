# Turn on the DeepSignal Console in 5 minutes

The installer serves the already-built DeepSignal Console through the ship server's existing nginx service; it does not alter OpenRVDAS data or processes.

## Turn it on and see it working

These are the three setup actions:

1. Run `sudo /opt/openrvdas/contrib/deepsignal/console/install/install.sh`.
2. Open `http://<server>/console/`, replacing `<server>` with the ship server name or address.
3. Read the **Self-test** page. Every healthy check says **Pass** and has a filled-circle shape; a failed check says **Down** and has a cross.

The command auto-detects the normal Ubuntu or RHEL nginx configuration, makes a timestamped backup, checks the complete nginx configuration, and reloads nginx. To inspect its proposed edit without root or any file change, add `--dry-run`. Nonstandard installations can use:

```sh
sudo ./install.sh --openrvdas-root /srv/openrvdas --nginx-conf /etc/nginx/conf.d/ship.conf
```

If a check is down, use **Copy report** and send the plain-text result to the technician responsible for the server. The report includes the cache URL, field and logger counts, cruise mode, newest-record age, and page-file result.

## Turn it off

```sh
sudo /opt/openrvdas/contrib/deepsignal/console/install/install.sh --uninstall
```

This removes only the nginx text between the `BEGIN deepsignal-console` and `END deepsignal-console` markers, tests nginx, and reloads it. Add `--no-reload` to either real command to print the reload command instead of running it.

## What it does not do

The installer does **not** change OpenRVDAS, logger configuration, running loggers, or supervisord. It does not build the console, install dependencies, open firewall ports, or change any nginx setting outside its marked location block.
