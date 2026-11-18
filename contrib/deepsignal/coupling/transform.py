"""Frozen-atlas live ship-contamination scoring transform."""

import copy
import json

from logger.transforms.transform import Transform
from logger.utils.das_record import DASRecord


class ShipCouplingTransform(Transform):
    """Annotate copies of records; never correct data or learn live."""

    def __init__(self, atlas_path, fields=None, min_verdict='ship_artifact',
                 suspect_threshold=.3, fail_threshold=.7):
        super().__init__()
        with open(atlas_path, encoding='utf-8') as stream:
            atlas = json.load(stream)
        self.fields = fields or list(atlas.get('polar', {}))
        self.thresholds = suspect_threshold, fail_threshold
        self.state = {}
        accepted = [h for h in atlas.get('hypotheses', [])
                    if h.get('status') == 'confirmed' and
                    h.get('invariance') == min_verdict]
        self.evidence = {h['field']: h for h in accepted}
        self.polar = atlas.get('polar', {})

    def transform(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            return [self.transform(item) for item in record]
        result = copy.deepcopy(record)
        fields = result.fields if isinstance(result, DASRecord) else result
        for name in ('relative_heading', 'sog', 'roll', 'pitch', 'heading_rate',
                     'rpm', 'thruster'):
            if name in fields:
                self.state[name] = fields[name]
        for field in self.fields:
            if field not in fields or field not in self.evidence:
                continue
            if 'relative_heading' not in self.state:
                fields[field + '_SHIP_QC'] = 2
                continue
            table = self.polar.get(field, [])
            sectors = max(12, max((row.get('sector', 0) for row in table), default=11) + 1)
            sector = int(float(self.state['relative_heading']) / (360 / sectors)) % sectors
            row = next((entry for entry in table if entry.get('sector') == sector), None)
            if row is None:
                fields[field + '_SHIP_QC'] = 2
                continue
            score = min(1.0, abs(float(row['median'])) /
                        max(abs(float(row.get('iqr', 1))), 1e-12))
            fields[field + '_SHIP'] = score
            evidence = self.evidence[field]
            fields[field + '_SHIP_why'] = (
                '%s, sector %d; confirmed replicated atlas evidence.' %
                (evidence['ship_variable'], sector))
            fields[field + '_SHIP_QC'] = (4 if score >= self.thresholds[1] else
                                          3 if score >= self.thresholds[0] else 1)
        return result
