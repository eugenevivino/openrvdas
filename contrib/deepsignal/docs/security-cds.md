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
3. Replace the existing nginx `/cds-ws` location with `security/nginx/cds-ws.conf` and include
   `security/nginx/security-headers.conf` in the HTTPS server block.
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
Use `--nginx-config` if nginx installs the snippet at another path. Use `--udp-port` and
`--udp-interface` when the CDS has a UDP feed. A failure line states the exposure, its effect, and
the setting to fix. After applying that fix, rerun the command. No restart of local loggers is
needed when only the gateway or nginx configuration changes.

Rejected browser messages receive `{"type":<type>,"status":403,"error":"read-only connection"}`.
Connections exceeding the message rate, field count, or connection count close with WebSocket
code 1008 and a plain reason. The gateway logs one connect line and one disconnect line with the
nginx identity headers, but it does not log field values.
