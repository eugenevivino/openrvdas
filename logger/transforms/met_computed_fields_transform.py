"""Meteorological and seawater functions for computed-field equations."""

from logger.transforms.computed_fields_transform import ComputedFieldsTransform
from logger.utils import met_formulas as met


class MetComputedFieldsTransform(ComputedFieldsTransform):
    """Compute fields with the standard expression functions and shipboard formulas."""

    FUNCTIONS = {
        **ComputedFieldsTransform.FUNCTIONS,
        'sat_vapor_pressure': met.sat_vapor_pressure,
        'dew_point': met.dew_point,
        'wet_bulb': met.wet_bulb,
        'sea_level_pressure': met.sea_level_pressure,
        'conductivity_ratio': met.conductivity_ratio,
        'salinity_pss78': met.salinity_pss78,
        'density_eos80_surface': met.density_eos80_surface,
        'sigma_t': met.sigma_t,
        'sound_speed_mackenzie': met.sound_speed_mackenzie,
    }
    if met.gsw is not None:
        FUNCTIONS.update(gsw_SA=met.gsw_SA, gsw_CT=met.gsw_CT)
