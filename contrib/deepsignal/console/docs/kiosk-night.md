# Kiosk Night

Kiosk Night keeps a bridge page selected and awake, and can change the console to Night automatically at civil dusk.

## Turn it on

Add `-kiosk` to a page hash, such as `#bridge-kiosk`, or configure a permanent page and optional automatic Night mode:

```yaml
modules:
  kiosk-night:
    kiosk_page: bridge
    auto_night: true
    latitude_field: S330Latitude
    longitude_field: S330Longitude
```

The position fields shown are the defaults. With kiosk mode active, page tabs and the Day/Dusk controls disappear. The Night button and brightness dimmer remain. Hold **Kiosk** for two seconds to exit. Confirm the screen remains awake; **Screen may sleep** means the browser or operating system refused the wake lock.

With `auto_night: true`, observe Night engage below −6° sun elevation and disengage after dawn. **Auto Night paused: position unavailable** means either position field is stale or has no data. A manual lighting choice remains in force until the next dawn or dusk crossing.

## What it does not do

Kiosk Night does not change operating-system kiosk settings, prevent a browser or operating system from denying wake lock, navigate between pages while locked, or estimate a position when ship position is unavailable.
