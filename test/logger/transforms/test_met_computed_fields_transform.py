import pytest

from logger.transforms.computed_fields_transform import (
    ComputedFieldsTransform, UnsafeExpressionError,
)
from logger.transforms.met_computed_fields_transform import MetComputedFieldsTransform


DEW_POINT_FIELDS = {'DewPoint': {'equation': 'dew_point(AirTemp, RH)'}}


def test_dew_point_expression():
    transform = MetComputedFieldsTransform(fields=DEW_POINT_FIELDS)
    assert transform.transform({'AirTemp': 20, 'RH': 50})['DewPoint'] == pytest.approx(
        9.2611, abs=1e-4, rel=0)


def test_none_omits_field():
    transform = MetComputedFieldsTransform(fields=DEW_POINT_FIELDS)
    assert transform.transform({'AirTemp': 20, 'RH': 0}) == {'AirTemp': 20, 'RH': 0}


@pytest.mark.parametrize('transform, name', [
    (MetComputedFieldsTransform, 'unknown_met_function'),
    (ComputedFieldsTransform, 'dew_point'),
])
def test_unknown_function_rejected(transform, name):
    with pytest.raises(UnsafeExpressionError, match=f'unknown function "{name}". Available:'):
        transform(fields={'DewPoint': {'equation': f'{name}(AirTemp, RH)'}})
