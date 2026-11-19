# Cached Data Server lockdown

The Cached Data Server accepts unauthenticated publish messages. Keep its TCP listener on
loopback so local loggers can use it directly. Browser displays connect through nginx and
the read-only WebSocket gateway.

The gateway passes `fields`, `describe`, `subscribe`, and `ready` requests only.
Subscriptions use explicit field names. The gateway relays CDS replies unchanged. A stopped
gateway interrupts displays while the CDS and local loggers continue running.

## Install and configure

1. Use `security/supervisor/cached_data_server.conf` for the `cached_data_server` program.
   The CDS defaults to `127.0.0.1:8766`. Leave off `--allow-non-loopback`. For UDP, set
   `CDS_UDP_PORTS` to the comma-separated feed ports and `CDS_UDP_INTERFACE` to the
   instrument interface's IPv4 address. Use `GROUP:PORT` for multicast. Remove both UDP
   arguments for a WebSocket-only CDS.
2. Install `security/supervisor/cds-gateway.conf` and reload supervisor. The gateway
   listens on `127.0.0.1:8767`.
3. Follow the console installer guide to deploy `deepsignal-console.conf`. Supply the
   browser's allowed origins. The managed site routes its exact `/cds-ws` path to
   the gateway and strips client-supplied `X-DS-User` and
   `X-DS-Role` headers. The gateway uses these headers only for logging.
   [Console installer guide](../console/docs/install.md)

## Check and diagnose

Run the console installer with `--check` and the deployment's original options. The
installer verifies the effective nginx configuration and the dedicated site's bytes.
Install runs the same runtime probe after nginx reloads.

The probe uses a non-loopback IPv4 address to require explicit refusals on TCP 8766
and 8767 and every configured CDS UDP port. A UDP timeout fails the check because
the probe cannot distinguish filtering from a listening feed. For multicast feeds it
probes the UDP port at the LAN address. The group and instrument interface continue
to carry the configured feed.

The probe requires HTTP 403 for foreign origins, including a request with a matching
unconfigured Host and Origin. It tries alternate WebSocket paths while the installer
checks adjacent nginx configuration for other routes or listeners. Through nginx the
probe checks the served console entrypoint for the same-origin `/cds-ws` configuration.

Each run publishes one timestamped nonce to the reserved
`deepsignal_gateway_self_test` field through the loopback CDS. It checks the value and
timestamp through nginx and reads the field back directly after the denied publish.
The probe leaves the reserved sample in the cache for normal expiry. Standalone runs
should be serialized with installer and Self-test runs on the same CDS.

To compare the site bytes directly, use the same rendering options with:

```sh
python -m contrib.deepsignal.security.check_cds --site-only \
    --nginx-site /etc/nginx/sites-enabled/deepsignal-console.conf \
    --origin http://ship.example
```

Malformed or disallowed gateway requests receive
`{"type":<type>,"status":403,"error":"read-only connection"}`.
The gateway caps browser requests at 65,536 bytes and upstream CDS messages at
1,048,576 bytes (1 MiB, `MAX_UPSTREAM_FRAME_BYTES`). It closes only the affected
browser connection with code 1009, using the reason `live-data server reply exceeds
size limit` for an oversize CDS reply. Wildcard subscriptions and connections
exceeding the rate, 200-field limit, or connection limit close with code 1008.
Connection logs omit field values.
