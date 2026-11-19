var e={id:`example`,presets:[{id:`example`,yaml:`title: Weather
tiles:
  - type: number
    label: Air temperature
    field: MwxAirTemp
    unit: °C
    decimals: 1
    # Optional. Set to the sensor's expected interval in seconds, e.g. period: 1.
    sparkline: 5
    wide: true
  - type: number
    label: Relative humidity
    field: MwxAirRelHumid
    unit: '%'
    decimals: 1
    sparkline: 5
`}]};export{e as default};