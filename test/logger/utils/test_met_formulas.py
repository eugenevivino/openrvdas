import pytest

from logger.utils import met_formulas as met


@pytest.mark.parametrize('formula, args, expected, tolerance', [
    (met.salinity_pss78, (1.888091, 40 / 1.00024, 10000), 40.0000, 1e-4),
    (met.salinity_pss78, (1, 15 / 1.00024, 0), 35.0000, 1e-4),
    (met.salinity_pss78, (1, 15, 0), 34.9968, 1e-4),
    (met.sound_speed_mackenzie, (25, 35, 1000), 1550.744, 1e-3),
    (met.density_eos80_surface, (0, 5), 999.96675, 1e-5),
    (met.density_eos80_surface, (35, 5), 1027.67547, 1e-5),
    (met.density_eos80_surface, (35, 25), 1023.34306, 1e-5),
    (met.sat_vapor_pressure, (20,), 23.3344, 1e-4),
    (met.dew_point, (20, 50), 9.2611, 1e-4),
    (met.dew_point, (30, 80), 26.1709, 1e-4),
    (met.dew_point, (10, 100), 10.0000, 1e-4),
    (met.wet_bulb, (20, 50), 13.6993, 1e-4),
    (met.wet_bulb, (30, 80), 27.1297, 1e-4),
    (met.sea_level_pressure, (1000, 15, 20), 1002.3740, 1e-4),
    (met.sea_level_pressure, (1013.25, 20, 0), 1013.2500, 1e-6),
    (met.conductivity_ratio, (42.914,), 1.0, 1e-12),
    (met.sigma_t, (35, 5), 27.67547, 1e-5),
])
def test_reference_value(formula, args, expected, tolerance):
    assert formula(*args) == pytest.approx(expected, abs=tolerance, rel=0)


@pytest.mark.parametrize('formula, args', [
    (met.dew_point, (20, 0)),
    (met.wet_bulb, (20, 2)),
    (met.salinity_pss78, (0, 15, 0)),
    (met.salinity_pss78, (0.01, 15, 0)),
    (met.salinity_pss78, (2, 15, 0)),
    (met.sound_speed_mackenzie, (25, 35, 9000)),
    (met.sea_level_pressure, (1000, 15, 101)),
    (met.sea_level_pressure, (1000, -273.15, 0)),
    (met.sat_vapor_pressure, (float('nan'),)),
    (met.conductivity_ratio, (float('inf'),)),
    (met.density_eos80_surface, (-1, 10)),
    (met.sigma_t, (-1, 10)),
])
def test_out_of_range(formula, args):
    assert formula(*args) is None


def test_gsw_conversions():
    gsw = pytest.importorskip('gsw', reason='gsw not installed', exc_type=ModuleNotFoundError)
    sa = met.gsw_SA(35, 100, -30, 45)
    assert sa == pytest.approx(gsw.SA_from_SP(35, 100, -30, 45))
    assert met.gsw_CT(sa, 10, 100) == pytest.approx(gsw.CT_from_t(sa, 10, 100))
    assert met.gsw_SA(35, 100, -30, 100) is None
    assert met.gsw_CT(-1, 10, 100) is None
