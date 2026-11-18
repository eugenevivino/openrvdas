# Cast view

The Cast view puts winch payout, tension, CTD depth, and distance above bottom on one night-safe screen.

## Configure it

Enable the `cast` page and map every ship-specific cache field in `console.yaml`:

```yaml
pages: [cast]
modules:
  cast:
    wire_out: WinchWireOut
    wire_speed: WinchWireSpeed
    tension: WinchTension
    ctd_depth: CtdDepth
    altimeter: CtdAltimeter
    swl: 4500
    warn_fraction: 0.8
    alarm_fraction: 0.95
    altimeter_warn: 10
    altimeter_alarm: 5
```

`swl` uses the same unit as the tension field and must be supplied by the ship. If it is omitted, the view says **SWL not set** and does not draw limit bands. Threshold values shown above are the defaults.

## Check it

Open **Cast** and compare its text values with the winch and CTD displays. Positive payout speed says **down**, negative speed says **up**, and the tension chart should accumulate 15 minutes of samples. Bring wire out below 5 m to begin a new cast and reset maximum tension.

## Limits

This display does not control the winch, determine the ship's safe working load, replace the winch's certified protection, or generate an audible alarm. Altimeter values outside 0–100 m are treated as **No bottom**.
