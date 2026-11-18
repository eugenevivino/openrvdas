"""Receive-only, bounded parser for selected PD0 ensemble health fields."""
import math
import struct
from datetime import datetime, timezone

try:
    from logger.transforms.transform import Transform
    from logger.utils.das_record import DASRecord
except ImportError:
    from openrvdas.logger.transforms.transform import Transform
    from openrvdas.logger.utils.das_record import DASRecord


class PD0SummaryTransform(Transform):
    """Summarize PD0 bytes without connecting to or controlling an ADCP."""

    MAX_BUFFER = 65536
    MAX_ENSEMBLE = 65534

    def __init__(self, beam_angle_deg):
        self.beam_angle_deg = float(beam_angle_deg)
        self.buffer = bytearray()
        self.checksum_failures = 0
        self.resyncs = 0
        self.last_adcp_time = None

    def transform(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            answers = []
            for item in record:
                value = self.transform(item)
                if isinstance(value, list):
                    answers.extend(value)
                elif value is not None:
                    answers.append(value)
            return answers
        raw, timestamp, template = self._input(record)
        if raw is None:
            return None
        self.buffer.extend(raw)
        if len(self.buffer) > self.MAX_BUFFER:
            dropped = len(self.buffer) - self.MAX_BUFFER
            del self.buffer[:dropped]
            self.resyncs += 1
        results = []
        while True:
            start = self.buffer.find(b'\x7f\x7f')
            if start < 0:
                if self.buffer:
                    self.resyncs += 1
                    self.buffer[:] = self.buffer[-1:] if self.buffer[-1] == 0x7f else b''
                break
            if start:
                del self.buffer[:start]
                self.resyncs += 1
            if len(self.buffer) < 6:
                break
            length = struct.unpack_from('<H', self.buffer, 2)[0]
            total = length + 2
            if length < 8 or total > self.MAX_ENSEMBLE:
                del self.buffer[0]
                self.resyncs += 1
                continue
            if len(self.buffer) < total:
                break
            ensemble = bytes(self.buffer[:total])
            del self.buffer[:total]
            expected = struct.unpack_from('<H', ensemble, length)[0]
            if sum(ensemble[:length]) & 0xffff != expected:
                self.checksum_failures += 1
                self.resyncs += 1
                continue
            fields = self._parse(ensemble, length)
            if fields is not None:
                results.append(self._output(template, timestamp, fields))
        if not results:
            return None
        return results[0] if len(results) == 1 else results

    @staticmethod
    def _input(record):
        if isinstance(record, bytes):
            return record, None, None
        if isinstance(record, bytearray):
            return bytes(record), None, None
        if isinstance(record, DASRecord):
            fields = record.fields
            raw = next((value for value in fields.values()
                        if isinstance(value, (bytes, bytearray))), None)
            return raw, record.timestamp, record
        if isinstance(record, dict):
            fields = record.get('fields', {})
            raw = next((value for value in fields.values()
                        if isinstance(value, (bytes, bytearray))), None)
            return raw, record.get('timestamp'), record
        return None, None, None

    def _parse(self, data, length):
        count = data[5]
        if 6 + 2 * count > length:
            return None
        offsets = struct.unpack_from('<' + 'H' * count, data, 6)
        variable = None
        bottom = None
        for offset in offsets:
            if offset + 2 > length:
                return None
            data_id = struct.unpack_from('<H', data, offset)[0]
            if data_id == 0x80 and offset + 28 <= length:
                variable = offset
            elif data_id == 0x600 and offset + 44 <= length:
                bottom = offset
        if variable is None:
            return None
        rtc = data[variable + 4:variable + 11]
        try:
            adcp_time = datetime(2000 + rtc[0], *rtc[1:6], rtc[6] * 10000,
                                 tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            adcp_time = None
        ensemble = (struct.unpack_from('<H', data, variable + 2)[0] +
                    (data[variable + 11] << 16))
        bit = struct.unpack_from('<H', data, variable + 12)[0]
        interval = None if self.last_adcp_time is None or adcp_time is None else (
            adcp_time - self.last_adcp_time)
        if adcp_time is not None:
            self.last_adcp_time = adcp_time
        now = datetime.now(timezone.utc).timestamp()
        fields = {
            'ADCP_Ensemble': ensemble,
            'ADCP_Time': adcp_time,
            'ADCP_Interval_s': interval,
            'ADCP_Heading': struct.unpack_from('<H', data, variable + 18)[0] * 0.01,
            'ADCP_Pitch': struct.unpack_from('<h', data, variable + 20)[0] * 0.01,
            'ADCP_Roll': struct.unpack_from('<h', data, variable + 22)[0] * 0.01,
            'ADCP_SoundSpeed': struct.unpack_from('<H', data, variable + 14)[0],
            'ADCP_XducerDepth': struct.unpack_from('<H', data, variable + 16)[0] * 0.1,
            'ADCP_BIT': bit,
            'ADCP_BITText': 'OK' if bit == 0 else ', '.join(
                'bit %d' % index for index in range(16) if bit & (1 << index)),
            'ADCP_BTDepth': None,
            'ADCP_BTGood': 0.0,
            'ADCP_ClockOffset_s': None if adcp_time is None else now - adcp_time,
            'ADCP_ChecksumFailures': self.checksum_failures,
            'ADCP_Resyncs': self.resyncs,
        }
        if bottom is not None:
            ranges = struct.unpack_from('<4H', data, bottom + 16)
            good = data[bottom + 40:bottom + 44]
            valid = [value * 0.01 for value, percent in zip(ranges, good)
                     if value and percent]
            fields['ADCP_BTGood'] = len(valid) * 25.0
            if len(valid) >= 3:
                fields['ADCP_BTDepth'] = (sum(valid) / len(valid) *
                                          math.cos(math.radians(self.beam_angle_deg)) +
                                          fields['ADCP_XducerDepth'])
        return fields

    @staticmethod
    def _output(template, timestamp, additions):
        if isinstance(template, DASRecord):
            return DASRecord(data_id=template.data_id, message_type=template.message_type,
                             timestamp=timestamp, fields={**template.fields, **additions},
                             metadata=dict(template.metadata))
        base = dict(template) if isinstance(template, dict) else {}
        base['timestamp'] = timestamp
        base['fields'] = {**base.get('fields', {}), **additions}
        return base
