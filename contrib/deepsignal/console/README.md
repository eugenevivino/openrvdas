# DeepSignal Console

## Turn it on in 5 minutes

DeepSignal shows live ship measurements from the OpenRVDAS data cache in a browser.

1. Follow [Install the DeepSignal Console](docs/install.md#configure-nginx-and-install), including the prerequisites at the top of the guide. Set the ship name and time zone in `dist/console.yaml`.
2. Open `/console/` on the ship server. The Weather tiles show readings from `MwxAirTemp` and `MwxAirRelHumid`. For different fields, use the page example below. Press **Night** or **N** to enter or leave Night mode. In Night mode, use **Red** or **Neutral** to select the palette and **Dim** to change brightness. Use keys **1–9** to switch pages.
3. Open **Self-test** to view the cache connection and the relay and UDP checks.

If the top bar keeps saying **Reconnecting**, check that the data cache and relay are running and that the console's nginx server routes `/cds-ws` to the relay. If a tile keeps waiting for data, compare its **Source** field name with the fields the ship logs. After editing either YAML file, reload the browser tab to pick up the changes.

### Try it without a ship

Use only a dedicated demo workstation with OpenRVDAS installed. Its nginx site must already serve a copy of `dist/` at `/console/` and route `/cds-ws` on the same origin to the read-only gateway at `127.0.0.1:8767`. Use free loopback ports `18766` and `8767` for the demo. Keep ship systems and existing services out of this setup.

From the OpenRVDAS folder, start the demo cache.

```sh
python3 -B -m contrib.deepsignal.console.demo_cache contrib/deepsignal/configs/console_demo_logger.yaml
```

The demo replays air temperature and humidity from the NBP1406 recording into a separate in-memory cache on `127.0.0.1:18766`. From the same folder in a second terminal, start the read-only gateway with the demo cache as its upstream.

```sh
python3 -B -m contrib.deepsignal.security.cds_gateway --upstream ws://127.0.0.1:18766
```

Leave `websocket` unset in the copy's `console.yaml`. Open `/console/` on the preconfigured nginx origin from the demo workstation. The browser uses the same host and port for `/cds-ws`, with `ws://` over HTTP and `wss://` over HTTPS.

The Weather tiles should update about once a second. Press **Ctrl+C** in the demo cache terminal to stop it. The top bar shows **Reconnecting** and how long ago the cache last replied. The tiles progress from **LIVE** to **AGING**, **STALE**, and **NO DATA** as their readings age. When finished, press **Ctrl+C** in the gateway terminal.

### Settings

| `console.yaml` setting | Default | Purpose |
| --- | --- | --- |
| `ship` | Required | Ship name shown in the top bar. |
| `ship_timezone` | `UTC` | IANA time zone for the ship clock. |
| `websocket` | `ws(s)://<browser-host>/cds-ws` | Same-origin address of the read-only relay. The console uses `wss://` over HTTPS and `ws://` over HTTP. |
| `pages` | `[]` | Page IDs to show, in tab order. An empty list shows all available pages. The sample configuration selects `example`. |
| `history` | `0` seconds | Initial history window. Tiles and routes can request more history. |
| `qc_suffix` | `_QC` | Suffix added to each field name to find its QARTOD flag and details. |
| `night_palette` | `red` | Initial Night palette. Set `neutral` for gray text with separate alarm and warning hues. |
| `modules` | `{}` | Settings by module ID, for example `modules: {example: {}}`. |
| `period` | `{}` | Expected update periods in seconds by field, for example `period: {MwxAirTemp: 1}`. A tile's own period takes precedence. |

Page IDs use lowercase letters, digits, and hyphens. A file in `pages/<id>.yaml` takes precedence over a module preset with the same ID, followed by auto-generated pages. Assign `order` to sort pages when `pages` is empty. The build generates `pages/index.json` from the shipped page files. If you add files after deployment and use `pages: []`, add their IDs to that JSON list.

For example, save the following as `pages/example.yaml` beside the console bundle to replace the Weather preset. Keep `example` in the `console.yaml` page list.

```yaml
title: Weather
tiles:
  - type: number
    label: Air temperature
    field: MwxAirTemp
    unit: °C
    decimals: 1
    sparkline: 5
    trend: 2
    period: 1
    logger: mwx1
```

For a number tile, supply `label`, `field`, and `unit`. `decimals` defaults to `1` and `wide` to `false`. Set `sparkline` or `trend` to a window in minutes. Trend shows direction and the change per expected update period. Use `compass: true` for an angular field in degrees to add a 16-point compass direction. `logger` supplies the field's logger when its cache metadata is incomplete. The console learns the period when neither the tile nor the field has an override. If a tile type is unavailable, `fallback: number` can use the same settings when they include the required number tile fields.

Night starts at 80% brightness and can be dimmed to 15%. Each browser remembers its mode, dimmer setting, and any palette selected on screen.

Without `period`, the console uses the median of up to 20 intervals, with a provisional one-second period until it has two readings. A reading stays **LIVE** for two periods and **AGING** through five. It stays visible as **STALE** until 60 periods or five minutes, whichever is later. **NO DATA** shows a dash and the last good reading, when known, with its time in UTC. The old `stale_after` setting can be removed from existing files. It has no effect.

Quality is shown separately from age. If the cache supplies a quality flag for the reading in `<field><qc_suffix>`, the quality badge shows **PASS**, **SUSPECT**, **FAIL**, **MISSING**, or **NOT EVALUATED**. Without a flag, it shows **NOT EVALUATED**. The last good reading has quality **PASS** or **NOT EVALUATED**. The cache can also provide per-test flags in `<field><qc_suffix>_<test>` and a reason in `<field><qc_suffix>_reason`. Logger health starts **UNKNOWN**. An installed adapter can update it independently of freshness and quality.

## What it does not do

- Start, stop, or change loggers, or write readings to the ship's cache.
- Provide a page editor or its own login.
- Replace a ship alarm or record new measurements. The display depends on the ship's existing data cache.
