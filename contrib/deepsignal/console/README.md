# DeepSignal Console

## Turn it on in 5 minutes

DeepSignal shows live ship measurements from the OpenRVDAS data cache in a browser.

1. Copy `dist/` to `/opt/openrvdas/contrib/deepsignal/console/dist/` on the ship server. Edit `dist/console.yaml` to set the ship name and time zone. The sample Weather page expects `MwxAirTemp` and `MwxAirRelHumid`. If your ship logs different fields, replace those names, labels and units in `dist/pages/example.yaml` with the ones your ship uses.
2. Check which OpenRVDAS nginx config exists, `/etc/nginx/sites-enabled/openrvdas.conf` on Ubuntu or `/etc/nginx/conf.d/openrvdas.conf` on RHEL. Put this block inside its existing `server { ... }` block.

   ```nginx
   location /console/ {
       alias /opt/openrvdas/contrib/deepsignal/console/dist/;
       try_files $uri $uri/ /console/index.html;
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

The demo replays air temperature and humidity from the NBP1406 recording into a separate in-memory cache. Serve a copy of `dist/` on the workstation using the nginx block above and add `websocket: ws://127.0.0.1:18766` to that copy's `console.yaml`. Open `http://127.0.0.1/console/` on the same workstation. The Weather tiles should update about once a second. Press **Ctrl+C** in the demo terminal to stop it. The top bar shows **Reconnecting** and the last reading age. The tiles progress from **LIVE** to **AGING**, **STALE**, and **NO DATA** as their readings age.

### Settings

| File | Required | Optional settings and defaults |
| --- | --- | --- |
| `console.yaml` | `ship` and `pages`. List page IDs in display order. | `ship_timezone` defaults to `UTC`, `websocket` to `ws://<browser-host>:8766`, `history` to `0` seconds, and `night_palette` to `red`. Set `night_palette: neutral` to select neutral lighting by default. For a console served over HTTPS, use the ship's `wss://` endpoint. |
| `pages/<page-id>.yaml` | A `title` and at least one tile. Set `type: number`, `label`, `field`, and `unit` on each tile. | `decimals` defaults to `1` and `wide` to `false`. Set `period` to the expected seconds between readings, for example `period: 2` or `period: 0.5`. The console learns the period when omitted. `sparkline` is off unless you set it to a number of minutes. A sparkline requests enough history for its window. |

Page IDs use lowercase letters, digits, and hyphens. To add a page, copy `pages/example.yaml`, edit its title and tiles, and add its filename without `.yaml` to `pages` in `console.yaml`. Night starts at 80% brightness and can be dimmed to 15%. Each browser remembers its mode, dimmer setting, and any palette selected on screen.

Without `period`, the console uses the median of up to 20 intervals, with a provisional one-second period until it has two readings. A reading stays **LIVE** for two periods and **AGING** through five. It stays visible as **STALE** until 60 periods or five minutes, whichever is later. **NO DATA** shows a dash and the last good reading, when known, with its time in UTC. The old `stale_after` setting can be removed from existing files. It has no effect.

Quality is shown separately from age. If the cache supplies a quality flag for the reading in `<field>_QC`, the quality badge shows **PASS**, **SUSPECT**, **FAIL**, **MISSING**, or **NOT EVALUATED**. Without a flag, it shows **NOT EVALUATED**. The last good reading is the most recent number marked **PASS** or **NOT EVALUATED**.

## What it does not do

- Start, stop, or change loggers, or write readings to the ship's cache.
- Provide an editor, maps, charts beyond sparklines, AI, or its own login.
- Replace a ship alarm or record new measurements. The display depends on the ship's existing data cache.
