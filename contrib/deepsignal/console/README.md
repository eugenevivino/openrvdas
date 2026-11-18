# DeepSignal Console

## Turn it on in 5 minutes

DeepSignal shows live ship measurements from the OpenRVDAS data cache in a browser.

1. Copy `dist/` to `/opt/openrvdas/contrib/deepsignal/console/dist/` on the ship server. Edit `dist/console.yaml` to set the ship name and time zone. The sample Weather page expects `MwxAirTemp` and `MwxAirRelHumid`. If your ship logs different fields, create `dist/pages/example.yaml` using the example below and set its field names, labels, and units.
2. Check which OpenRVDAS nginx config exists, `/etc/nginx/sites-enabled/openrvdas.conf` on Ubuntu or `/etc/nginx/conf.d/openrvdas.conf` on RHEL. Put this block inside its existing `server { ... }` block.

   ```nginx
   location /console/ {
       alias /opt/openrvdas/contrib/deepsignal/console/dist/;
       try_files $uri $uri/ =404;
   }
   ```

   Run `sudo nginx -t && sudo systemctl reload nginx`.
3. Open `http://<ship-server>/console/`. The Weather tiles show numbers with units and the top bar says **Live** when current readings arrive. Press **Night** or **N** to enter or leave Night mode. In Night mode, use **Red** or **Neutral** to select the palette and **Dim** to change brightness. Use keys **1–9** to switch pages in the order listed in `console.yaml`.

If the top bar keeps saying **Reconnecting**, check that the data cache is running and that its address in `console.yaml` is reachable from the display. If a tile keeps waiting for data, compare its **Source** field name with the fields the ship logs. After editing either YAML file, reload the browser tab to pick up the changes.

To turn the console off, remove the `location /console/` block you added and run `sudo nginx -t && sudo systemctl reload nginx` again. You can leave the folder in place for next time. The ship's data cache and loggers keep running.

### Try it without a ship

On a workstation with OpenRVDAS installed, run this from the OpenRVDAS folder.

```sh
python3 -B -m contrib.deepsignal.console.demo_cache contrib/deepsignal/configs/console_demo_logger.yaml
```

The demo replays air temperature and humidity from the NBP1406 recording into a separate in-memory cache. Serve a copy of `dist/` on the workstation using the nginx block above and add `websocket: ws://127.0.0.1:18766` to that copy's `console.yaml`. Open `http://127.0.0.1/console/` on the same workstation. The Weather tiles should update about once a second. Press **Ctrl+C** in the demo terminal to stop it. The top bar shows **Reconnecting** and how long ago the cache last replied. The tiles progress from **LIVE** to **AGING**, **STALE**, and **NO DATA** as their readings age.

### Settings

| `console.yaml` setting | Default | Purpose |
| --- | --- | --- |
| `ship` | Required | Ship name shown in the top bar. |
| `ship_timezone` | `UTC` | IANA time zone for the ship clock. |
| `websocket` | `ws://<browser-host>:8766` | Address of the data cache. Use the ship's `wss://` endpoint if serving the console over HTTPS. |
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
