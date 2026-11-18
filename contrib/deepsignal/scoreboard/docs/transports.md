# Scoreboard transports

Choose one transport `type` and provide its settings to the scoreboard writer.
The writer integration is delivered separately.

* `serial`: set `port` and, when needed, baud rate, parity, byte size, stop bits,
  flow control, and write timeout. Exclusive access defaults to enabled.
* `rs485`: accepts serial settings plus RTS direction levels and optional delays.
* `tcp`: set `host` and `port`; connection and send timeouts are configurable.
* `udp`: set `host` and `port`; enable `broadcast` only for broadcast addresses.
* `modbus_rtu`: set serial options and `response_timeout`.
* `modbus_tcp`: set `host`; port defaults to 502 and timeouts are configurable.

All transports accept `inter_frame_delay` in seconds. A connection is opened on
the first send. Any link, reply, or protocol failure raises `TransportError` and
closes the connection so the caller can apply its reconnect policy.

For a USB adapter with automatic RS-485 direction control, use `type: serial`.
Use `type: rs485` only when the operating-system driver supports RTS direction
control. Confirm polarity and direction delays against the adapter manual.

Modbus register values must be integers from 0 through 65535. Each write holds
1 through 123 consecutive registers. Unit 0 on RTU is a broadcast and has no
reply. Verify unit addresses and register maps against the scoreboard manual.
