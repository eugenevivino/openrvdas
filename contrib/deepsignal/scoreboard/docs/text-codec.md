# Text scoreboard codec

Use the text codec for a board whose protocol is a formatted line or page of text.
Select `codec: text` in the board profile. No vendor-specific Python is needed.

## Limits

Set `lines` and `chars_per_line`. Overlong lines are rejected, never truncated.
Choose `charset: ascii`, `upper`, or `digits_sign_point`. Unsupported characters
become `replace_char`, which defaults to `?`.

## Framing

Put the byte-level frame in `framing.template`. Escapes such as `\x02`, `\r`, and
`\n` produce control bytes. With the default `frame_per: line`, templates may use
`{line}`, `{line_number}`, and `{address}`. With `frame_per: page`, they may use
`{page}`, `{line1}` through the configured line count, and `{address}`. Configure
`line_separator` for the text between page lines.

Formatting widths work for plain fields, for example `{address:02d}`. Attribute,
index, nested, and unknown field access is rejected.

## Address and checksum

Set `addressing.default` and an inclusive two-value `addressing.range` when the
template uses `{address}`. A caller may override the default address.

Insert one exact `{checksum}` placeholder where checksum bytes belong. Configure
`checksum`, `checksum_format`, and optionally `checksum_from`. The checksum covers
the formatted head beginning at the first occurrence of `checksum_from`. An empty
value starts at byte zero.

## Startup frames

Each string in `init_frames` is unescaped directly to bytes. Startup frames are
not template-formatted.
