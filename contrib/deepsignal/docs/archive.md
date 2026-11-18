# Lossless archive compression

DeepSignal archives closed plain-text logs without changing their contents. It verifies every compressed
copy against the original SHA-256 before optionally deleting the original. The default keeps originals.
Files younger than one hour and files with today's UTC date in their name are always left alone.

## Plan, compress, and verify

Preview first. This command writes nothing:

```sh
python -m contrib.deepsignal.archive plan /data/openrvdas
```

Compress with the automatic codec choice, then verify all manifest entries:

```sh
python -m contrib.deepsignal.archive compress /data/openrvdas
python -m contrib.deepsignal.archive verify /data/openrvdas
```

Automatic mode uses `zstd` when the command is installed and xz otherwise. Explicit choices are
`--codec zstd`, `--codec xz`, and `--codec gzip`. Only use `--delete-originals` after testing the
retention policy. Each log directory receives an append-only `MANIFEST.sha256` containing both hashes,
both sizes, the codec, level, and tool version. `--out /archive` mirrors the source tree there.

## Measured NBP1406 ratios

Measurements concatenate the 20 files under `test/NBP1406/*/raw/*` (6,736,819 bytes) before applying
the fixed production settings. This avoids counting a container header once per small source file.

| Codec | Compressed bytes | Raw/compressed ratio | Setting |
| --- | ---: | ---: | --- |
| gzip | 968,953 | 6.95x | level 9, `mtime=0` |
| xz | 584,036 | 11.53x | preset 9 |
| zstd | not measured | not measured | level 19, `--long=27`; tool unavailable in test environment |

The automatic fallback was therefore xz. Measure zstd aboard ship before choosing it explicitly.

## Shore bundles

Copy `contrib/deepsignal/configs/archive_bundle.yaml`, then edit `cruise`, `root`, priorities, byte
budgets, and globs. Priorities must be integers 1 through 5. Files are considered in sorted order and a
file that would exceed its priority's budget is omitted. Bundles and their JSON manifests are written to
the output directory:

```sh
python -m contrib.deepsignal.archive bundle ship-archive.yaml /data/openvdm-extra
```

In OpenVDM, add `/data/openvdm-extra` as an **Extra Directory**. Add a **Ship-to-Shore** rule for that
directory, set the transfer priority to match the bundle filename's `p1` through `p5`, and set the
bandwidth cap appropriate for the satellite link. Priority 1 should contain manifests and snapshots;
bulk logs should use a later priority. OpenVDM transfers the compressed files as ordinary files.

## Recovery and errors

`.gz`, `.xz`, and `.zst` are standard gzip, xz, and Zstandard streams. Keep the adjacent manifests.
`verify` reports the manifest and entry that fails and exits without altering either copy. Configuration
errors use one line naming the setting, observed value, expected value, and an example.
