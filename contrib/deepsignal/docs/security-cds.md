# Cached Data Server lockdown

## What this protects

The Cached Data Server accepts unauthenticated publish messages. It must never be reachable from
the ship network. This overlay keeps local loggers connected directly to the CDS and gives browser
displays a separate read-only WebSocket gateway.

The gateway passes `fields`, `describe`, `subscribe`, and `ready` requests only. Subscriptions use
explicit field names. The gateway relays CDS replies unchanged. A stopped gateway interrupts
displays while the CDS and local loggers continue running.

## Install and configure

1. Use `security/supervisor/cached_data_server.conf` as the `cached_data_server` program entry.
   Set `CDS_UDP_PORTS` in the supervisord environment to the comma-separated list of feed ports
   and set `CDS_UDP_INTERFACE` to the instrument interface's IPv4 address. A multicast feed uses
   `GROUP:PORT` and joins that group on the same interface. Remove both UDP arguments for a
   WebSocket-only CDS. The CDS defaults to `127.0.0.1:8766` and rejects a non-loopback TCP address
   unless `--allow-non-loopback` is explicitly supplied. Leave that override off in this deployment.
2. Install `security/supervisor/cds-gateway.conf`, adjusting its working directory if needed.
3. Replace the existing nginx `/cds-ws` location with `security/nginx/cds-ws.conf` for Django
   or `security/nginx/cds-ws-react.conf` for React. Both serve the exact same-origin `/cds-ws`
   path through the read-only relay on `127.0.0.1:8767`. Include `security-headers.conf` in the
   HTTPS server block.
4. Reload supervisor and nginx, then run the check below.

The gateway accepts connections on `127.0.0.1:8767` only. Remote clients use nginx. Nginx strips
client-supplied `X-DS-User` and `X-DS-Role` headers, and the gateway uses these headers only for
logging. Local processes can reach the loopback listener directly.

## Check and diagnose

Run:

```text
python -m contrib.deepsignal.security.check_cds
```

The command prints one sentence for each check and returns a nonzero status if any check fails.
The nginx check starts at `/etc/nginx/nginx.conf` by default. Use `--nginx-config PATH` for a
different main configuration and `--nginx-react-config PATH` to check a second configuration.
Includes are resolved relative to the main configuration directory. The checker examines all HTTP
and stream proxy destinations and upstream members, rejects unresolved destinations, and requires
the relay’s same-origin guard. Use `--console-source PATH` to verify the URL builder and the
complete `loadConsole` function in the deployed checkout’s `src/pages.ts`. The checker requires
the supported source form through the return of the console configuration.

Supply `--gateway-url ws://ship.example/cds-ws` to probe nginx. The live check requires an HTTP 403
handshake response for a foreign Origin and tests publish refusal and subscription with the
console’s own Origin. It uses a trusted loopback publish to seed the subscription probe. Use
`--udp-port` and `--udp-interface` when the CDS has a UDP feed. Rerun the command after applying a
reported fix.

Malformed and disallowed requests receive `{"type":<type>,"status":403,"error":"read-only connection"}`.
The WebSocket server closes with code 1009 for browser messages larger than 65,536 bytes. Wildcard
subscriptions and connections exceeding the message rate, 200-field limit, or connection count
close with code 1008. The gateway logs connection and disconnection with the nginx identity headers
and omits field values.
