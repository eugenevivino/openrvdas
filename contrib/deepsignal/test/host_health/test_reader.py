import unittest

from contrib.deepsignal.host_health.host_health_reader import (
    HostHealthReader,
    parse_chronyc_tracking,
    parse_meminfo,
    parse_supervisor_status,
)


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class DiskUsage:
    total = 1000
    free = 250


class TestProbes(unittest.TestCase):
    def test_meminfo(self):
        text = 'MemTotal:       1000 kB\nMemAvailable:    375 kB\n'
        self.assertEqual(parse_meminfo(text), 37.5)

    def test_chronyc_csv(self):
        text = 'ABC,1,2,0.125,4,5,6\n'
        self.assertEqual(parse_chronyc_tracking(text), 0.125)

    def test_supervisor_recent_restart(self):
        text = ('stable RUNNING pid 1, uptime 2 days, 1:02:03\n'
                'recent RUNNING pid 2, uptime 0:00:12\n'
                'stopped STOPPED Not started\n')
        self.assertEqual(parse_supervisor_status(text, 60), 1)


class TestHostHealthReader(unittest.TestCase):
    def make_reader(self, **overrides):
        clock = overrides.pop('clock', FakeClock())
        values = {
            'interval': 30,
            'disk_paths': {'root': '/'},
            'clock': clock,
            'disk_usage_reader': lambda path: DiskUsage(),
            'file_text_reader': lambda path: (
                'MemTotal: 1000 kB\nMemAvailable: 500 kB\n'
                if path == '/proc/meminfo' else '321.5 0.0\n'),
            'command_runner': lambda args: (
                'ABC,1,2,-0.25,4\n' if args[0] == 'chronyc'
                else 'recent RUNNING pid 2, uptime 0:00:12\n'),
            'command_finder': lambda command: '/usr/bin/' + command,
        }
        values.update(overrides)
        return HostHealthReader(**values), clock

    def test_record_shape_and_all_fields(self):
        reader, _ = self.make_reader()
        record = reader.read()
        self.assertEqual(record.data_id, 'host')
        self.assertEqual(record.timestamp, 130.0)
        self.assertEqual(record.fields, {
            'host_clock_offset_s': -0.25,
            'host_disk_free_gb_root': 250 / 1024 ** 3,
            'host_disk_free_pct_root': 25.0,
            'host_load1': reader._loadavg_reader()[0],
            'host_mem_available_pct': 50.0,
            'host_supervisor_restarts': 1,
            'host_uptime_s': 321.5,
        })

    def test_interval_is_honored(self):
        reader, clock = self.make_reader()
        reader.read()
        clock.now += 5
        reader.read()
        self.assertEqual(clock.sleeps, [30, 25])

    def test_missing_commands_omit_fields(self):
        reader, _ = self.make_reader(command_finder=lambda command: None)
        with self.assertLogs(level='INFO') as messages:
            fields = reader.read().fields
        self.assertNotIn('host_clock_offset_s', fields)
        self.assertNotIn('host_supervisor_restarts', fields)
        self.assertIn('chronyc command is unavailable', '\n'.join(messages.output))

    def test_probe_exception_omits_only_its_field(self):
        def broken_disk(path):
            raise OSError('disk unavailable')

        reader, _ = self.make_reader(disk_usage_reader=broken_disk)
        with self.assertLogs(level='WARNING'):
            fields = reader.read().fields
        self.assertNotIn('host_disk_free_pct_root', fields)
        self.assertIn('host_mem_available_pct', fields)

    def test_failures_log_once_per_type(self):
        reader, _ = self.make_reader(file_text_reader=lambda path: (_ for _ in ()).throw(OSError()))
        with self.assertLogs(level='WARNING') as messages:
            reader.read()
            reader.read()
        failures = [line for line in messages.output if 'memory probe failed' in line]
        self.assertEqual(len(failures), 1)


if __name__ == '__main__':
    unittest.main()
