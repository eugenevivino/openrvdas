# Cached Data Server lockdown

## What this protects

The Cached Data Server accepts unauthenticated publish messages. It must never be reachable from
the ship network. This overlay keeps local loggers connected directly to the CDS and gives browser
displays a separate read-only WebSocket gateway.

The gateway passes `fields`, `describe`, `subscribe`, and `ready` requests only. It rejects every
other request with a plain JSON 403 response. It never changes messages flowing from the CDS to a
display. A stopped gateway interrupts displays but does not interrupt the CDS or local loggers.

## Install and configure

1. Start the CDS with `--host 127.0.0.1`. If UDP input is enabled, also set `--udp_interface` to
   the address of the intended feed interface. Do not use `0.0.0.0`.
2. Install `security/supervisor/cds-gateway.conf`, adjusting its working directory if needed.
3. Replace the existing nginx `/cds-ws` location with `security/nginx/cds-ws.conf` for Django
   or `security/nginx/cds-ws-react.conf` for React. Both serve the exact same-origin `/cds-ws`
   path through the read-only relay on `127.0.0.1:8767`. Include `security-headers.conf` in the
   HTTPS server block.
4. Reload supervisor and nginx, then run the check below.

The `X-DS-User` and `X-DS-Role` headers are only logged in this version. They are trusted because
the gateway listens on loopback and nginx removes client-supplied copies. Do not bind the gateway
to a ship-facing address.

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

Rejected browser messages receive `{"type":<type>,"status":403,"error":"read-only connection"}`.
Connections exceeding the message rate, field count, or connection count close with WebSocket
code 1008 and a plain reason. The gateway logs one connect line and one disconnect line with the
nginx identity headers, but it does not log field values.
