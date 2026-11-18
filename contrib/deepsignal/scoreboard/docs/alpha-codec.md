# Alpha codec

The Alpha codec converts one rendered scoreboard page into one Alpha Write
TEXT frame. It does not open a serial port or configure sign memory.

## Profile settings

Set `codec: alpha`. The codec reads these framing keys:

* `type_code`, default `Z`
* `file_label`, default `A`
* `sync`, either `nul` or `soh`, default `nul`
* `checksum`, default `true`
* `line_separator`, default one space, with contract escape syntax supported
* `mode`, an optional mapping with one-character `position` and `code` values

Set `addressing.default` to an integer from 0 through 255 or a two-character
hex string. A constructor address overrides it. Address 0 is broadcast.

The limits mapping supplies `chars_per_line`, `charset`, and `replace_char`.
The `upper` charset uppercases text. The `digits_sign_point` charset permits
digits, spaces, plus, minus, and decimal point. Other characters are replaced.
All protocol control characters in cell text are also replaced.

## Bench procedure

1. Start with the sign disconnected and verify its address and baud setting.
2. Generate a frame from a short page and inspect its bytes before sending.
3. Confirm the checksum behavior and the selected file label.
4. Confirm every configured mode on the target sign.
5. Confirm multi-line separation on the target sign.
6. Only then mark the profile `verified: bench`.

Keep the delay between bytes below one second. Alpha 2.0 signs document baud
rates from 1200 through 38400. Use `init()` only as a no-op in this version.
