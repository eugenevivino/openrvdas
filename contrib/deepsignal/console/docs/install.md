# Install the DeepSignal Console

Build the console into `contrib/deepsignal/console/dist/` in the OpenRVDAS deployment and
start the CDS and its read-only gateway. The console installer serves those assets and
`/cds-ws` from a dedicated nginx site.

Stage the installer, its Python helpers, the nginx template, the checker and the CDS
probe in a root-owned release such as `/opt/deepsignal-release`. Keep the files and
their parent directories free of symlinks and group or other write permission.
The installer and its CDS probe use `/opt/openrvdas/venv/bin/python`. To use another
root-managed OpenRVDAS virtualenv, set `DEEPSIGNAL_PYTHON` to the absolute path of its
Python executable in the installer's environment. The installer stops if this
interpreter is unavailable or cannot import `websockets`.

## Configure nginx and install

Remove old `/cds-ws` routes and other listeners or proxies that expose the CDS or gateway.
The nginx `http` block must load the dedicated `deepsignal-console.conf` site once through
an existing wildcard include. The installer looks for the site under `sites-enabled/`
and `conf.d/` beside the main configuration, in that order. Use `--nginx-site PATH` to
select another directory with an active include and keep the filename
`deepsignal-console.conf`. Use `--nginx-main PATH` if the running nginx service uses a
main configuration other than `/etc/nginx/nginx.conf`.

```sh
sudo /opt/deepsignal-release/contrib/deepsignal/console/install/install.sh \
    --origin http://ship.example
```

Open `http://ship.example/console/` and view **Self-test**. Use **Copy report** to share
the result with the server technician.

Pass one `--origin` for each browser origin. Origins use concrete hostnames or IPv4
addresses, share a scheme and port, and omit paths and default ports. For HTTPS, supply
`--ssl-certificate` and `--ssl-certificate-key` with absolute paths. The probe uses
the host's trusted certificate authorities. Use `--openrvdas-root` if the deployed
console is outside `/opt/openrvdas`.

The installer reads all UDP feed ports from
`/etc/supervisor/conf.d/cached_data_server.conf`. Use `--cds-supervisor-config PATH`
if that fragment is installed elsewhere. When the command uses the shipped Supervisor
environment substitutions, the installer resolves them from the running CDS process.
Run the Self-test command with permission to read that process's environment.

The installer inventories the effective nginx configuration and lists conflicting or
unclassifiable files before writing the site. It checks the running systemd nginx
service and refuses an existing site with group or other write permission. It reloads
nginx even when the site already has the expected bytes and confirms that a new
worker generation is active. It then probes the reloaded site using the host's
default-route IPv4 address. Use `--probe-address ADDRESS` to select a LAN address where
CDS UDP feeds should be unreachable. Use `--probe-source ADDRESS` to bind a second
local address. The default vhost on the console listener must return 403 on `/cds-ws`
for matching unconfigured Host and Origin values.

Use `--dry-run` with the same options to preview the change. On a host without nginx,
the preview inventories the configuration files and their includes directly. Use
`--render` to print the expected site.

## Check or remove the site

Repeat the install command with the same configuration options and add `--check` to
verify the installed site, live gateway and served console bundle. Each failed probe
check prints a reason and the command exits non-zero. Add `--uninstall` to remove the
dedicated site and reload nginx. To change the site's parameters, uninstall with the
previous parameters before installing with the new ones.
