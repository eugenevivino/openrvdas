"""Writer for a deliberately minimal, documented P1/11-style CSV subset."""

import datetime

try:
    from logger.utils.das_record import DASRecord
    from logger.writers.writer import Writer
except ImportError:  # Current core package layout.
    from openrvdas.logger.utils.das_record import DASRecord
    from openrvdas.logger.writers.writer import Writer


class P111Writer(Writer):
    """Write one line's shot positions to a P1/11-style CSV file."""

    def __init__(self, filename, ship_name, encoding='utf-8'):
        super().__init__(encoding=encoding)
        self._file = open(filename, 'w', encoding=encoding, newline='')
        self._file.write('# P1/11 subset, verify with the processing team before delivery\n')
        self._file.write('# CRS: WGS 84 (EPSG:4326)\n')
        self._file.write('# Units: degrees, UTC\n')
        self._file.write(f'# Ship: {ship_name}\n')
        self._file.write('shot_number,fire_time_utc,latitude_deg,longitude_deg\n')

    def write(self, record):
        if record is None:
            return None
        if isinstance(record, list):
            return [self.write(item) for item in record]
        fields = record.fields if isinstance(record, DASRecord) else record.get('fields', {})
        required = ('SHOT_Number', 'SHOT_FireTime', 'SHOT_Lat', 'SHOT_Lon')
        if any(fields.get(name) is None for name in required):
            return None
        timestamp = datetime.datetime.fromtimestamp(
            float(fields['SHOT_FireTime']), datetime.timezone.utc)
        time_text = timestamp.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        line = (f"{fields['SHOT_Number']},{time_text},{float(fields['SHOT_Lat']):.8f},"
                f"{float(fields['SHOT_Lon']):.8f}\n")
        self._file.write(line)
        self._file.flush()
        return record

    def close(self):
        self._file.close()
