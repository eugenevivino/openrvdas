# Data release policy

`ReleasePolicyTransform` filters a copy of each outbound record by audience and
holds configured fields back while the vessel is inside an EEZ. Its EEZ state
comes from a boolean field produced by `GeofenceTransform` (or another trusted
source). Until that field is seen, the transform fails closed by treating the
vessel as inside and logs one warning.

**Never put this transform in front of the raw logfile writer.** Put it only in
front of outbound shore streams, public pages, or ERDDAP writers. For example:

```yaml
writers:
  public_writer:
    class: ComposedWriter
    transforms:
      - class: ReleasePolicyTransform
        module: contrib.deepsignal.release_policy.transform
        kwargs:
          policy_path: contrib/deepsignal/configs/release_policy_example.yaml
    writer:
      class: TextFileWriter
      kwargs:
        filename: /var/tmp/public_records.json
```

The ordered `levels` globs use their first match; `default_level` handles fields
with no match. Audience order is `public < science < shore_ops`. Inside an EEZ,
`hold_back` applies to every audience. Configured positions remain available but
are rounded. Output includes a short SHA-256 policy fingerprint in
`release_policy`. Use this to inspect a field:

```sh
python -m contrib.deepsignal.release_policy explain POLICY.yaml TSG_Temperature
```

This module is not legal advice, does not decide treaty requirements, does not
delete raw data, and does not implement retention. Each ship or cruise must
write and review its own policy. Apply it only to copies headed off ship.
