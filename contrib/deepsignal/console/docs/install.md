# Turn on the DeepSignal Console in 5 minutes

The installer serves the already-built DeepSignal Console through the ship server's existing nginx service.

## Stage the installer and relay checker

#197 must land before deploying the console with live data. Stage a trusted release at `/opt/deepsignal-release`. The release must include `contrib/deepsignal/console/install/install.sh`, its sibling `nginx-site.awk`, and `contrib/deepsignal/security/check_cds.py` from #197. These files and each directory on their paths must be root-owned and free of symlinks and group or other write permission. The stock installer assigns the `/opt/openrvdas` deployment to `rvdas`. That deployment supplies the console assets. The root-owned release supplies the installer and checker. Use a root-managed Python installation with the #197 checker's existing `websockets` dependency available.

Configure the selected nginx virtual host with `security/nginx/cds-ws.conf` for Django or `security/nginx/cds-ws-react.conf` for React, then load that configuration before running the installer. Both snippets serve `/cds-ws` through the #197 relay on `127.0.0.1:8767`. Use a concrete `server_name` that matches the browser hostname. The check connects to the host's first `listen` address and port using that name and validates TLS for HTTPS. Use `--server-name NAME` to select one server if the file contains several. If the cache receives UDP, pass `--udp-port PORT --udp-interface ADDRESS`.

## Turn it on and see it working

These are the three setup actions:

1. Run `sudo /opt/deepsignal-release/contrib/deepsignal/console/install/install.sh`.
2. Open `http://<server>/console/`, replacing `<server>` with the ship server name or address.
3. Read the **Self-test** page. Every healthy check says **Pass** and has a filled-circle shape; a failed check says **Down** and has a cross.

The command auto-detects the normal Ubuntu or RHEL nginx site, makes a timestamped backup, checks the configuration, and reloads nginx. It uses `nginx -T` to find the main configuration and verifies the proposed site within that configuration. The nginx service must use the same main configuration as the installer’s `nginx -T` and `nginx -t` commands. Use `--dry-run` to preview the proposed edit and run the static nginx check without writing the site. Nginx needs permission to read its configuration and certificates during the preview. Use `--nginx-conf` to select a different site file that the main configuration loads.

```sh
sudo /opt/deepsignal-release/contrib/deepsignal/console/install/install.sh \
    --openrvdas-root /srv/openrvdas --nginx-conf /etc/nginx/conf.d/ship.conf
```

Use `--check` with the same server and UDP options to rerun the relay gate without editing nginx. Every install checks the effective configuration, including included files, sibling HTTP hosts, and stream proxies. It rejects direct CDS destinations and proxy targets it cannot resolve statically. When the selected host has no relay, the installer adds a 503 fallback after that check passes. When the relay exists, the installer verifies the same-origin guard and requires nginx to refuse a foreign-Origin WebSocket handshake with HTTP 403. It also checks the same-origin URL from its construction through the return from `loadConsole` in `src/pages.ts` under the checkout supplied by `--openrvdas-root`.

If a check is down, use **Copy report** and send the plain-text result to the technician responsible for the server. The report includes the cache URL, field and logger counts, cruise mode, newest-record age, and page-file result.

## Turn it off

```sh
sudo /opt/deepsignal-release/contrib/deepsignal/console/install/install.sh --uninstall
```

This removes only the nginx text between the `BEGIN deepsignal-console` and `END deepsignal-console` markers, tests nginx, and reloads it. Add `--no-reload` to either real command to print the reload command instead of running it.

## What it does not do

The installer does **not** change OpenRVDAS, logger configuration, running loggers, or supervisord. It does not build the console, install dependencies, open firewall ports, or change any nginx setting outside its marked location block.
