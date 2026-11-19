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
   browser's allowed origins and every configured UDP port. The managed site routes its
   exact `/cds-ws` path to the gateway and strips client-supplied `X-DS-User` and
   `X-DS-Role` headers. The gateway uses these headers only for logging.
   [Console installer guide](../console/docs/install.md)

## Check and diagnose

Run the console installer with `--check` and the deployment's original options. The
installer verifies the effective nginx configuration and the checker compares the
dedicated site's bytes against the template rendered with those options. The checker
then checks the CDS binds and probes the gateway for foreign-Origin rejection,
publish refusal and subscription through nginx.

To compare the site bytes directly, use the same rendering options with:

```sh
python -m contrib.deepsignal.security.check_cds --site-only \
    --nginx-site /etc/nginx/sites-enabled/deepsignal-console.conf \
    --origin http://ship.example
```

Malformed or disallowed gateway requests receive
`{"type":<type>,"status":403,"error":"read-only connection"}`.
The gateway closes with code 1009 for messages larger than 65,536 bytes. Wildcard
subscriptions and connections exceeding the rate, 200-field limit, or connection limit
close with code 1008. Connection logs omit field values.
