"""Record-time ADCP comparisons using only passively received values."""
from collections import deque

try:
    from logger.transforms.transform import Transform
    from logger.utils.das_record import DASRecord
except ImportError:
    from openrvdas.logger.transforms.transform import Transform
    from openrvdas.logger.utils.das_record import DASRecord


def _circular(value, reference):
    return (value - reference + 180.0) % 360.0 - 180.0


class ADCPCrossCheckTransform(Transform):
    """Compare ADCP health values with configured independent references."""

    def __init__(self, roles, heading_threshold=1.0, sv_threshold=2.0,
                 depth_threshold_pct=3.0, frozen_s=60, overlap_window_s=0.1,
                 persistence_s=30, clear_s=30, stale_s=30):
        self.roles = dict(roles)
        self.heading_threshold = float(heading_threshold)
        self.sv_threshold = float(sv_threshold)
        self.depth_threshold_pct = float(depth_threshold_pct)
        self.frozen_s = float(frozen_s)
        self.overlap_window_s = float(overlap_window_s)
        self.persistence_s = float(persistence_s)
        self.clear_s = float(clear_s)
        self.stale_s = float(stale_s)
        self.last_seen = {}
        self.heading_anchor = None
        self.gyro_anchor = None
        self.heading_since = None
        self.bad_since = None
        self.clear_since = None
        self.alarm = False
        self.pings = deque()

    def transform(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            return [self.transform(item) for item in record]
        is_das = isinstance(record, DASRecord)
        timestamp = record.timestamp if is_das else record.get('timestamp')
        incoming = record.fields if is_das else record.get('fields', {})
        values = {role: incoming.get(name) for role, name in self.roles.items()}
        for role, value in values.items():
            if value is not None:
                self.last_seen[role] = timestamp
        stale = any(timestamp - seen > self.stale_s for seen in self.last_seen.values())
        out = {'ADCPX_HeadingDiff_gyro': self._diff(values, 'gyro_heading'),
               'ADCPX_HeadingDiff_gnss': self._diff(values, 'gnss_heading'),
               'ADCPX_SVDiff_tsg': self._subtract(values, 'adcp_sv', 'tsg_sv'),
               'ADCPX_SVDiff_probe': self._subtract(values, 'adcp_sv', 'probe_sv'),
               'ADCPX_BTvsMB_pct': self._depth(values),
               'ADCPX_PingOverlap': self._overlap(values, timestamp),
               'ADCPX_Stale': stale}
        frozen, turn = self._frozen(values, timestamp)
        out['ADCPX_HeadingFrozen'] = frozen
        failures = []
        for label in ('gyro', 'gnss'):
            value = out['ADCPX_HeadingDiff_' + label]
            if value is not None and abs(value) > self.heading_threshold:
                failures.append('%s heading difference %.1f degrees exceeds %.1f' %
                                (label, value, self.heading_threshold))
        for label in ('tsg', 'probe'):
            value = out['ADCPX_SVDiff_' + label]
            if value is not None and abs(value) > self.sv_threshold:
                failures.append('%s sound speed difference %.1f m/s exceeds %.1f' %
                                (label, value, self.sv_threshold))
        depth_difference = out['ADCPX_BTvsMB_pct']
        if (depth_difference is not None and
                abs(depth_difference) > self.depth_threshold_pct):
            failures.append('bottom track versus multibeam %.1f%% exceeds %.1f%%' %
                            (out['ADCPX_BTvsMB_pct'], self.depth_threshold_pct))
        if frozen:
            elapsed = timestamp - self.heading_since
            failures.append(
                'ADCP heading stuck at %.1f for %.0f seconds while the gyro turned %.0f '
                'degrees. Check the heading feed into UHDAS.' %
                (values['adcp_heading'], elapsed, turn))
        self._alarm_state(bool(failures), timestamp)
        out['ADCPX_Alarm'] = self.alarm
        out['ADCPX_AlarmText'] = '; '.join(failures) if self.alarm else ''
        return self._output(record, incoming, out)

    def _diff(self, values, reference):
        if values.get('adcp_heading') is None or values.get(reference) is None:
            return None
        return _circular(values['adcp_heading'], values[reference])

    @staticmethod
    def _subtract(values, first, second):
        if values.get(first) is None or values.get(second) is None:
            return None
        return values[first] - values[second]

    @staticmethod
    def _depth(values):
        if values.get('adcp_bt_depth') is None or not values.get('mb_depth'):
            return None
        return (values['adcp_bt_depth'] - values['mb_depth']) / values['mb_depth'] * 100.0

    def _overlap(self, values, timestamp):
        for role in ('mb_ping_time', 'ek_ping_time'):
            if values.get(role) is not None:
                self.pings.append(values[role])
        while self.pings and self.pings[0] < timestamp - 300:
            self.pings.popleft()
        if values.get('adcp_time') is None:
            return 0
        return sum(abs(values['adcp_time'] - ping) <= self.overlap_window_s
                   for ping in self.pings)

    def _frozen(self, values, timestamp):
        heading = values.get('adcp_heading')
        gyro = values.get('gyro_heading')
        if heading is None or gyro is None:
            return False, 0
        if self.heading_anchor is None or abs(_circular(heading, self.heading_anchor)) > 0.001:
            self.heading_anchor = heading
            self.gyro_anchor = gyro
            self.heading_since = timestamp
            return False, 0
        turn = abs(_circular(gyro, self.gyro_anchor))
        return timestamp - self.heading_since >= self.frozen_s and turn > 1.0, turn

    def _alarm_state(self, bad, timestamp):
        if bad:
            self.clear_since = None
            if self.bad_since is None:
                self.bad_since = timestamp
            if timestamp - self.bad_since >= self.persistence_s:
                self.alarm = True
        else:
            self.bad_since = None
            if self.alarm:
                if self.clear_since is None:
                    self.clear_since = timestamp
                if timestamp - self.clear_since >= self.clear_s:
                    self.alarm = False

    @staticmethod
    def _output(record, incoming, additions):
        fields = {**incoming, **additions}
        if isinstance(record, DASRecord):
            return DASRecord(data_id=record.data_id, message_type=record.message_type,
                             timestamp=record.timestamp, fields=fields,
                             metadata=dict(record.metadata))
        result = dict(record)
        result['fields'] = fields
        return result
