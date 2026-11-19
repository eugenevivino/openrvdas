# Install the DeepSignal Console

Build the console into `contrib/deepsignal/console/dist/` in the OpenRVDAS deployment and
start the CDS and its read-only gateway. The console installer serves those assets and
`/cds-ws` from a dedicated nginx site.

Stage the installer, its Python helpers, the nginx template and the CDS checker in a
root-owned release such as `/opt/deepsignal-release`. Keep the files and their parent
directories free of symlinks and group or other write permission. Use a root-managed Python
with the existing `websockets` dependency.

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
`--ssl-certificate` and `--ssl-certificate-key` with absolute paths. For a CDS UDP feed,
pass every feed port with a separate `--udp-port` and supply `--udp-interface ADDRESS`.
Use `--openrvdas-root` if the deployed console is outside `/opt/openrvdas`.

The installer inventories the effective nginx configuration and lists conflicting or
unclassifiable files before writing the site. It checks the running systemd nginx
service, reloads it even when the site already has the expected bytes, and confirms that
a new worker generation is active. Use `--dry-run` with the same options to preview the
change. On a host without nginx, the preview inventories the configuration files and
their includes directly. Use `--render` to print the expected site.

## Check or remove the site

Repeat the install command with the same configuration options and add `--check` to
verify the installed site and gateway. Add `--uninstall` to remove the dedicated site and
reload nginx. To change the site's parameters, uninstall with the previous parameters
before installing with the new ones.
