"""Reader that publishes local host health as a DASRecord."""

import logging
import os
import shutil
import subprocess
import time

from logger.readers.reader import Reader
from logger.utils import formats
from logger.utils.das_record import DASRecord


def parse_meminfo(text):
    """Return available memory as a percentage from proc meminfo text."""
    values = {}
    for line in text.splitlines():
        if ':' in line:
            name, value = line.split(':', 1)
            values[name] = float(value.split()[0])
    return 100.0 * values['MemAvailable'] / values['MemTotal']


def parse_chronyc_tracking(text):
    """Return chronyc CSV's last clock offset, in seconds."""
    fields = text.strip().splitlines()[0].split(',')
    return float(fields[3])


def _uptime_seconds(value):
    days = 0
    if ' day' in value:
        day_text, value = value.split(',', 1)
        days = int(day_text.split()[0])
    parts = [int(part) for part in value.strip().split(':')]
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError('unexpected supervisor uptime')
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def parse_supervisor_status(text, restart_window):
    """Count running supervisord programs younger than restart_window."""
    count = 0
    for line in text.splitlines():
        if ' RUNNING ' not in line or 'uptime ' not in line:
            continue
        uptime = line.split('uptime ', 1)[1]
        if _uptime_seconds(uptime) < restart_window:
            count += 1
    return count


def _run_command(args):
    result = subprocess.run(args, capture_output=True, check=True, text=True,
                            timeout=5, shell=False)
    return result.stdout


class HostHealthReader(Reader):
    """Periodically sample disk, memory, load, uptime, and service health."""

    def __init__(self, interval=30, disk_paths=None, logfile_root='/var/log/openrvdas',
                 restart_window=300, clock=None, disk_usage_reader=None,
                 file_text_reader=None, command_runner=None, command_finder=None,
                 loadavg_reader=None):
        super().__init__(output_format=formats.Python_Record)
        self.interval = self._positive_number('interval', interval, '30')
        self.restart_window = self._positive_number(
            'restart_window', restart_window, '300')
        if disk_paths is None:
            disk_paths = {'root': '/', 'log': logfile_root}
        if not isinstance(disk_paths, dict) or not disk_paths:
            raise ValueError("setting disk_paths saw %r; expected a non-empty mapping, "
                             "for example {'root': '/'}" % (disk_paths,))
        for name, path in disk_paths.items():
            if not isinstance(name, str) or not name.replace('_', '').isalnum():
                raise ValueError("setting disk_paths name saw %r; expected a short name "
                                 "using letters, numbers, or underscores, for example 'log'" % name)
            if not isinstance(path, str) or not path:
                raise ValueError("setting disk_paths[%s] saw %r; expected a path string, "
                                 "for example '/var/log/openrvdas'" % (name, path))
        self.disk_paths = dict(disk_paths)
        self._clock = clock or time
        self._disk_usage = disk_usage_reader or shutil.disk_usage
        self._read_text = file_text_reader or self._default_read_text
        self._run = command_runner or _run_command
        self._find_command = command_finder or shutil.which
        self._loadavg_reader = loadavg_reader or os.getloadavg
        self._next_sample = self._clock.time() + self.interval
        self._reported = set()

    @staticmethod
    def _positive_number(name, value, example):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError('setting %s saw %r; expected a positive number, for example %s'
                             % (name, value, example))
        return float(value)

    @staticmethod
    def _default_read_text(path):
        with open(path, encoding='utf-8') as input_file:
            return input_file.read()

    def _log_once(self, failure_type, level, message, *args):
        if failure_type not in self._reported:
            self._reported.add(failure_type)
            logging.log(level, message, *args)

    def _add_disk(self, fields):
        for name, path in self.disk_paths.items():
            try:
                usage = self._disk_usage(path)
                fields['host_disk_free_pct_' + name] = 100.0 * usage.free / usage.total
                fields['host_disk_free_gb_' + name] = usage.free / (1024.0 ** 3)
            except Exception as error:
                self._log_once('disk:' + name, logging.WARNING,
                               'disk probe failed for %s: %s', path, error)

    def _add_file_probes(self, fields):
        try:
            fields['host_mem_available_pct'] = parse_meminfo(
                self._read_text('/proc/meminfo'))
        except Exception as error:
            self._log_once('memory', logging.WARNING, 'memory probe failed: %s', error)
        try:
            fields['host_uptime_s'] = float(
                self._read_text('/proc/uptime').split()[0])
        except Exception as error:
            self._log_once('uptime', logging.WARNING, 'uptime probe failed: %s', error)

    def _add_load(self, fields):
        try:
            fields['host_load1'] = self._loadavg_reader()[0]
        except Exception as error:
            self._log_once('load', logging.WARNING, 'load probe failed: %s', error)

    def _add_command_probe(self, fields, command, args, field, parser):
        if not self._find_command(command):
            self._log_once(command + ':missing', logging.INFO,
                           '%s command is unavailable; omitting %s', command, field)
            return
        try:
            fields[field] = parser(self._run(args))
        except Exception as error:
            self._log_once(command, logging.WARNING, '%s probe failed: %s', command, error)

    def read(self):
        """Wait for the sampling deadline and return one host DASRecord."""
        delay = self._next_sample - self._clock.time()
        if delay > 0:
            self._clock.sleep(delay)
        timestamp = self._clock.time()
        self._next_sample = max(self._next_sample + self.interval,
                                timestamp + self.interval)
        fields = {}
        self._add_disk(fields)
        self._add_file_probes(fields)
        self._add_load(fields)
        self._add_command_probe(fields, 'chronyc', ['chronyc', '-c', 'tracking'],
                                'host_clock_offset_s', parse_chronyc_tracking)
        self._add_command_probe(
            fields, 'supervisorctl', ['supervisorctl', 'status'],
            'host_supervisor_restarts',
            lambda output: parse_supervisor_status(output, self.restart_window))
        return DASRecord(data_id='host', timestamp=timestamp, fields=fields)
