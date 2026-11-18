"""Scalar meteorological and seawater formulas. Invalid readings return None."""

import math

try:
    import gsw
except ModuleNotFoundError as exc:
    if exc.name != 'gsw':
        raise
    gsw = None


def sat_vapor_pressure(t_c):
    """Saturation vapor pressure (hPa) over water, for -40 to 50 degC."""
    if -40 <= t_c <= 50:
        return 6.1094 * math.exp(17.625 * t_c / (t_c + 243.04))
    return None


def dew_point(t_c, rh_pct):
    """Magnus dew point (degC) for -40 to 50 degC and 0 < RH <= 100 percent."""
    if not (-40 <= t_c <= 50 and 0 < rh_pct <= 100):
        return None
    # Subtract the logs to avoid underflow when RH is a subnormal float.
    g = math.log(rh_pct) - math.log(100) + 17.625 * t_c / (243.04 + t_c)
    return 243.04 * g / (17.625 - g)


def wet_bulb(t_c, rh_pct):
    """Stull wet bulb (degC) for -20 to 50 degC and 5 to 99 percent RH."""
    if not (-20 <= t_c <= 50 and 5 <= rh_pct <= 99):
        return None
    return (t_c * math.atan(0.151977 * math.sqrt(rh_pct + 8.313659))
            + math.atan(t_c + rh_pct) - math.atan(rh_pct - 1.676331)
            + 0.00391838 * rh_pct**1.5 * math.atan(0.023101 * rh_pct) - 4.686035)


def sea_level_pressure(p_hpa, t_c, h_m):
    """Pressure (hPa) reduced from 0 to 100 m, for finite p > 0 hPa and t > -273.15 degC."""
    if not (0 < p_hpa < math.inf and -273.15 < t_c < math.inf and 0 <= h_m <= 100):
        return None
    t_k = t_c + 273.15
    # Algebraically equivalent to 1 - lapse / (t_k + lapse), without cancellation.
    result = p_hpa * (t_k / (t_k + 0.0065 * h_m))**-5.257
    return result if math.isfinite(result) else None


def conductivity_ratio(c_ms_cm):
    """PSS-78 conductivity ratio for finite conductivity >= 0 mS/cm."""
    if 0 <= c_ms_cm < math.inf:
        return c_ms_cm / 42.914
    return None


def _polynomial(x, coefficients):
    """Evaluate coefficients in ascending order of power using Horner's rule."""
    value = 0.0
    for coefficient in reversed(coefficients):
        value = value * x + coefficient
    return value


def salinity_pss78(c_ratio, t90_c, p_dbar):
    """Practical salinity (2 to 42 PSU) from positive finite R, ITS-90 degC and 0 to 10000 dbar.

    The temperature range after conversion to IPTS-68 is -2 to 40 degC.
    """
    t = 1.00024 * t90_c
    if not (0 < c_ratio < math.inf and -2 <= t <= 40 and 0 <= p_dbar <= 10000):
        return None
    rt = _polynomial(t, (0.6766097, 2.00564e-2, 1.104259e-4, -6.9698e-7, 1.0031e-9))
    p = p_dbar
    rp = 1 + p * (2.070e-5 + p * (-6.370e-10 + p * 3.989e-15)) / (
        1 + 3.426e-2 * t + 4.464e-4 * t**2 + (4.215e-1 - 3.107e-3 * t) * c_ratio)
    x = math.sqrt(c_ratio / (rp * rt))
    # The UNESCO polynomials are in successive powers of sqrt(Rt).
    base = _polynomial(x, (0.0080, -0.1692, 25.3851, 14.0941, -7.0261, 2.7081))
    delta = _polynomial(x, (0.0005, -0.0056, -0.0066, -0.0375, 0.0636, -0.0144))
    salinity = base + (t - 15) / (1 + 0.0162 * (t - 15)) * delta
    return salinity if 2 <= salinity <= 42 else None


def density_eos80_surface(s, t_c):
    """One-atmosphere density (kg/m³) for 0 to 42 PSU and -2 to 40 degC on IPTS-68."""
    if not (0 <= s <= 42 and -2 <= t_c <= 40):
        return None
    t = t_c
    rho_w = (999.842594 + 6.793952e-2 * t - 9.095290e-3 * t**2 + 1.001685e-4 * t**3
             - 1.120083e-6 * t**4 + 6.536332e-9 * t**5)
    a = 0.824493 - 4.0899e-3 * t + 7.6438e-5 * t**2 - 8.2467e-7 * t**3 + 5.3875e-9 * t**4
    b = -5.72466e-3 + 1.0227e-4 * t - 1.6546e-6 * t**2
    return rho_w + s * a + s**1.5 * b + 4.8314e-4 * s**2


def sigma_t(s, t_c):
    """Surface density minus 1000 (kg/m³) for 0 to 42 PSU and -2 to 40 degC on IPTS-68."""
    density = density_eos80_surface(s, t_c)
    return None if density is None else density - 1000


def sound_speed_mackenzie(t_c, s, depth_m):
    """Sound speed (m/s) for 2 to 30 degC, 25 to 40 PSU and depth 0 to 8000 m."""
    if not (2 <= t_c <= 30 and 25 <= s <= 40 and 0 <= depth_m <= 8000):
        return None
    return (1448.96 + 4.591 * t_c - 5.304e-2 * t_c**2 + 2.374e-4 * t_c**3
            + 1.340 * (s - 35) + 1.630e-2 * depth_m + 1.675e-7 * depth_m**2
            - 1.025e-2 * t_c * (s - 35) - 7.139e-13 * t_c * depth_m**3)


if gsw is not None:
    def gsw_SA(sp, p_dbar, lon, lat):
        """Absolute salinity (g/kg) for 0-42 PSU, 0-10000 dbar, -180..360° E and -90..90° N."""
        if not (0 <= sp <= 42 and 0 <= p_dbar <= 10000 and -180 <= lon <= 360 and -90 <= lat <= 90):
            return None
        sa = float(gsw.SA_from_SP(sp, p_dbar, lon, lat))
        return sa if math.isfinite(sa) else None

    def gsw_CT(sa, t_c, p_dbar):
        """Conservative Temperature (degC) for 0-50 g/kg, -2..40 degC ITS-90 and 0-10000 dbar."""
        if not (0 <= sa <= 50 and -2 <= t_c <= 40 and 0 <= p_dbar <= 10000):
            return None
        ct = float(gsw.CT_from_t(sa, t_c, p_dbar))
        return ct if math.isfinite(ct) else None
