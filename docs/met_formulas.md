# Meteorological and seawater fields

`MetComputedFieldsTransform` adds the following functions to computed-field equations.
Python callers can also import them from `logger.utils.met_formulas`. Each takes scalar
readings and returns a float. An out-of-range or nonfinite reading returns `None`,
so the transform omits that calculation for the record. Range endpoints are inclusive
unless marked with an inequality.

| Function | Inputs and supported range | Result | Source |
| --- | --- | --- | --- |
| `sat_vapor_pressure(t_c)` | Air temperature −40 to 50 °C | Saturation vapor pressure over water, hPa | Alduchov & Eskridge (1996) |
| `dew_point(t_c, rh_pct)` | Air temperature −40 to 50 °C, 0 < relative humidity ≤ 100% | Dew point, °C | Inverse of the same Magnus formula |
| `wet_bulb(t_c, rh_pct)` | Air temperature −20 to 50 °C, relative humidity 5 to 99% | Estimated wet-bulb temperature, °C | Stull (2011), eq. 1 |
| `sea_level_pressure(p_hpa, t_c, h_m)` | Station pressure > 0 hPa, air temperature > −273.15 °C, barometer height above sea level 0 to 100 m | Sea-level pressure, hPa | Constant-lapse-rate barometric formula, using the specified 0.0065 K/m and exponent 5.257 |
| `conductivity_ratio(c_ms_cm)` | Conductivity ≥ 0 mS/cm | Dimensionless ratio to 42.914 mS/cm | UNESCO (1983), PSS-78 reference conductivity |
| `salinity_pss78(c_ratio, t90_c, p_dbar)` | Positive conductivity ratio, ITS-90 temperature corresponding to −2 to 40 °C on IPTS-68, sea pressure 0 to 10000 dbar | Practical salinity, 2 to 42 (commonly labeled PSU) | UNESCO (1983), PSS-78 |
| `density_eos80_surface(s, t_c)` | Practical salinity 0 to 42, IPTS-68 temperature −2 to 40 °C | One-atmosphere density, kg/m³ | UNESCO (1981), EOS-80 |
| `sigma_t(s, t_c)` | Same salinity and IPTS-68 temperature as surface density | Surface density minus 1000, kg/m³ | UNESCO (1981), EOS-80 |
| `sound_speed_mackenzie(t_c, s, depth_m)` | Temperature 2 to 30 °C, practical salinity 25 to 40, depth 0 to 8000 m | Sound speed, m/s | Mackenzie (1981), nine-term equation |
| `gsw_SA(sp, p_dbar, lon, lat)` | Practical salinity 0 to 42, sea pressure 0 to 10000 dbar, longitude −180 to 360° east, latitude −90 to 90° north | Absolute Salinity, g/kg | TEOS-10, GSW `SA_from_SP` |
| `gsw_CT(sa, t_c, p_dbar)` | Absolute Salinity 0 to 50 g/kg, ITS-90 in-situ temperature −2 to 40 °C, sea pressure 0 to 10000 dbar | Conservative Temperature, °C | TEOS-10, GSW `CT_from_t` |

The two TEOS-10 names are available when the optional `gsw` package is installed.
The ranges above describe the wrappers' operating limits.
For an ITS-90 sensor, pass its temperature directly to `salinity_pss78`. For EOS-80
density and sigma-t, convert to IPTS-68 first with `1.00024 * WaterTemp90`.

## Example logger

This configuration reads one JSON object per line from `weather.jsonl` and writes
JSON to standard output. With input `{"AirTemp": 20, "RH": 50}`, the output includes
a dew point of 9.26 °C and a wet bulb of 13.70 °C.

```yaml
readers:
  class: TextFileReader
  kwargs:
    file_spec: weather.jsonl
transforms:
  - class: FromJSONTransform
  - class: MetComputedFieldsTransform
    module: logger.transforms.met_computed_fields_transform
    kwargs:
      fields:
        DewPoint:
          equation: dew_point(AirTemp, RH)
        WetBulb:
          equation: wet_bulb(AirTemp, RH)
  - class: ToJSONTransform
writers:
  class: TextFileWriter
```

## References

- Alduchov and Eskridge (1996), “Improved Magnus Form Approximation of Saturation Vapor Pressure,” *Journal of Applied Meteorology* 35, 601–609.
- Stull (2011), “Wet-Bulb Temperature from Relative Humidity and Air Temperature,” *Journal of Applied Meteorology and Climatology* 50, 2267–2269.
- NOAA, NASA and USAF (1976), *U.S. Standard Atmosphere, 1976*, part 1, hydrostatic pressure in a layer with a linear temperature profile.
- Fofonoff and Millard (1983), *Algorithms for Computation of Fundamental Properties of Seawater*, UNESCO Technical Papers in Marine Science 44.
- UNESCO (1981), *Background Papers and Supporting Data on the International Equation of State of Seawater 1980*, UNESCO Technical Papers in Marine Science 38.
- Mackenzie (1981), “Nine-term equation for sound speed in the oceans,” *Journal of the Acoustical Society of America* 70, 807–812.
- IOC, SCOR and IAPSO (2010), *The International Thermodynamic Equation of Seawater – 2010*, IOC Manuals and Guides 56, and the Gibbs SeaWater Oceanographic Toolbox.
