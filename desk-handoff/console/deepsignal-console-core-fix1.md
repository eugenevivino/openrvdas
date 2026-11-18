# Brief addendum: deepsignal-console-core fix round 1

Lead decision 2026-11-18 after the first job stopped at the two-round rule. Fresh session,
`gpt-6.2-sol` high, same scratch dir and the uncommitted work tree as it stands. Read
`deepsignal-console-core.md` (the full brief) and this file. Everything in the brief still applies.

## Verified cause of the red lighting tests
Environment, not logic: Node 25 ships a built-in `localStorage` that shadows jsdom's,
so `window.localStorage.clear` is missing in Vitest. Running with
`NODE_OPTIONS=--no-experimental-webstorage` makes 8 of 8 pass. Fix it in the repo so
plain `npm run test` passes on Node 22 LTS and Node 25: set the flag in the test script
(or Vitest `execArgv`/pool options), not by changing test logic. Do not stub away the
storage behaviour under test.

## Missing text the first job asked for
- Usability items: `USABILITY.md` (copied beside this file). Answer 1 to 14 in the report.
- nginx block for the README, verbatim (Vite `base` must be `/console/`):
```
location /console/ {
    alias /opt/openrvdas/contrib/deepsignal/console/dist/;
    try_files $uri $uri/ /console/index.html;
}
```
  Say where it goes: inside the existing `server { ... }` block of the OpenRVDAS nginx
  config (`/etc/nginx/sites-enabled/openrvdas.conf` on Ubuntu, `/etc/nginx/conf.d/openrvdas.conf`
  on RHEL; tell the reader to check which exists), then `sudo nginx -t && sudo systemctl reload nginx`.
  Then open `http://<ship-server>/console/`.

## Finish in this order
1. Test fix above; full acceptance command 1 green, including `npm run build` and committed `dist/`.
2. Sample logger config `contrib/deepsignal/configs/console_demo_logger.yaml` and README sections.
3. Live test: Playwright for Python is now installed in the scratch venv by the lead. It must
   actually run (not skip) and pass.
4. Impeccable audit in Day, Dusk and Night red, `IMPECCABLE-REPORT.md`.

## Stop rule
Two rounds in this job still red: stop and report exactly which command fails and why.
