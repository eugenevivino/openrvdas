"""Read host clock synchronization state without elevated privileges."""

import re
import subprocess


def _default_runner(command, **kwargs):
    return subprocess.run(command, **kwargs)


class HostTimeHealth:
    """Query chrony, then systemd-timesyncd, for host clock health."""

    def __init__(self, runner=None):
        self.runner = runner or _default_runner

    @staticmethod
    def _unknown():
        return {
            'provider': 'unknown', 'synced': False, 'offset_s': None,
            'rms_offset_s': None, 'stratum': None, 'leap_status': 'unknown',
            'reference': None,
        }

    def _run(self, command):
        try:
            return self.runner(command, capture_output=True, text=True,
                               timeout=2, check=False)
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return None

    @staticmethod
    def _chrony(output):
        values = {}
        for line in output.splitlines():
            parts = [part.strip() for part in line.split(',')]
            if len(parts) >= 2:
                values[parts[0]] = parts[1:]
        try:
            offset = float(values['System time'][0])
            description = ' '.join(values['System time'][1:]).lower()
            if 'slow' in description:
                offset = -offset
            leap = values['Leap status'][0]
            reference_parts = values.get('Reference ID', [None, None])
            reference = reference_parts[1] if len(reference_parts) > 1 else reference_parts[0]
            return {
                'provider': 'chrony',
                'synced': leap.lower() == 'normal',
                'offset_s': offset,
                'rms_offset_s': float(values['RMS offset'][0]),
                'stratum': int(values['Stratum'][0]),
                'leap_status': leap,
                'reference': reference or None,
            }
        except (KeyError, ValueError, IndexError):
            return None

    @staticmethod
    def _timesyncd(output):
        values = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        message = values.get('NTPMessage', '')
        stratum_match = re.search(r'\bStratum=(\d+)', message)
        leap_match = re.search(r'\bLeap=(\d+)', message)
        if not stratum_match:
            return None
        stratum = int(stratum_match.group(1))
        leap = int(leap_match.group(1)) if leap_match else None
        return {
            'provider': 'systemd-timesyncd',
            'synced': stratum > 0 and leap != 3,
            'offset_s': None,
            'rms_offset_s': None,
            'stratum': stratum,
            'leap_status': str(leap) if leap is not None else 'unknown',
            'reference': values.get('ServerName') or values.get('ServerAddress'),
        }

    def read(self):
        """Return the first usable synchronization report."""
        result = self._run(['chronyc', '-c', 'tracking'])
        if result is not None and result.returncode == 0:
            health = self._chrony(result.stdout)
            if health:
                return health
        result = self._run(['timedatectl', 'show-timesync'])
        if result is not None and result.returncode == 0:
            health = self._timesyncd(result.stdout)
            if health:
                return health
        return self._unknown()
