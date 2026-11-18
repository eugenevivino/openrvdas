# Modbus scoreboard codec

The Modbus codec converts rendered page cells into register writes. It does
not open a connection or send bytes. Select a Modbus RTU or Modbus TCP
transport separately.

Set `addressing.default` to the display unit id from 0 through 247. A unit id
passed to `ModbusCodec` overrides that default.

Add entries to `framing.registers` in the order they must be written. Each
entry identifies a one-based `line`, a zero-based `cell`, the target register
`address`, and a `type`. Supported types are `int16`, `uint16`, `int32`,
`uint32`, and `float32`.

Use `scale` to convert engineering values before integer rounding. Integer
values round halfway away from zero. For a two-word type, set `word_order` to
`big` for the high word first or `little` for the low word first.

Set `stale_value` to the exact unscaled register value that represents no
data. The codec uses it when a cell is missing, stale, null, nonnumeric, or
not finite. It validates every stale value when the codec is constructed, so
an invalid profile fails before operation.

Live values outside their register type raise an error. The codec never
clamps or wraps an out-of-range reading.
