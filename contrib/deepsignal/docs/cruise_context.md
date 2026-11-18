# Cruise context

Cruise context imports the current cruise metadata from OpenVDM or Sealog without writing to either
service. The generated YAML records explicit null values for missing source fields. Verify the source
field shape against a live OpenVDM 2.17 installation before operational use.

## One-time import

```shell
python -m contrib.deepsignal.cruise_context pull --openvdm http://openvdm --out cruise.yaml
```

The command refuses to replace an existing file. Preview a change with `--diff cruise.yaml`; diff mode
does not write a file. Sealog runtime access takes its JWT from the environment variable named by
`token_env`. Tokens are used only in the Authorization header and are not included in object displays.

## Runtime tagging

Use `contrib/deepsignal/configs/cruise_context_openvdm.yaml` as a configuration example. The transform
adds `cruise_id`, `lowering_id`, `cruise_active`, and `cruise_context_stale` to each record's fields.
An outage after a successful poll retains the last context and sets the stale flag. An initial outage
is raised because there is no trustworthy context to retain.

OpenVDM lowering endpoints may need to be combined by a deployment adapter because the documented
cruise-config request does not itself guarantee lowering fields. A live-system check is required.
