# Chart module

The chart module shows live underway measurements as strip charts and leaves visible gaps when samples stop.

## Turn it on

Enable the built-in `science` page, or add a chart tile to a ship page:

```yaml
title: Science
tiles:
  - type: chart
    field: TsgTemp
    label: Sea surface temperature
    unit: degC
    decimals: 2
    window: 30 min
    period: 1
    wide: true
    size: large
```

Open the page and confirm the current value, quality and freshness appear above the plot. A feed interruption longer than three median sample intervals appears as a gap; stale data ends with **NO DATA**. Suspect or failed samples have hollow markers.

The module does not interpolate missing samples, set fixed Y-axis limits, persist history beyond the store's six-hour buffer, or diagnose an instrument failure.
