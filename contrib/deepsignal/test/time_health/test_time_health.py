import datetime
import subprocess
import unittest

from contrib.deepsignal.time_health.host import HostTimeHealth
from contrib.deepsignal.time_health.streams import TimeHealthTransform


UTC = datetime.timezone.utc


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        response = self.responses[command[0]]
        if isinstance(response, Exception):
            raise response
        return subprocess.CompletedProcess(command, *response)


class TestHostTimeHealth(unittest.TestCase):
    def test_chrony_synced_parse(self):
        output = ('Reference ID,7F7F0101,GNSS\nStratum,2\nSystem time,0.125000000,'
                  'seconds fast of NTP time\nRMS offset,0.200000000,seconds\nLeap status,Normal\n')
        health = HostTimeHealth(FakeRunner({'chronyc': (0, output, '')})).read()
        self.assertEqual('chrony', health['provider'])
        self.assertTrue(health['synced'])
        self.assertEqual(0.125, health['offset_s'])
        self.assertEqual(0.2, health['rms_offset_s'])
        self.assertEqual(2, health['stratum'])
        self.assertEqual('GNSS', health['reference'])

    def test_chrony_unsynced_parse(self):
        output = ('Reference ID,00000000,\nStratum,0\nSystem time,0.0,seconds fast '
                  'of NTP time\nRMS offset,0.0,seconds\nLeap status,Not synchronised\n')
        health = HostTimeHealth(FakeRunner({'chronyc': (0, output, '')})).read()
        self.assertFalse(health['synced'])
        self.assertEqual('Not synchronised', health['leap_status'])

    def test_unreachable_and_timeout_are_unknown(self):
        unavailable = subprocess.CompletedProcess([], 1, '', 'not running')
        timeout = subprocess.TimeoutExpired(['timedatectl'], 2)
        runner = FakeRunner({'chronyc': (unavailable.returncode, '', unavailable.stderr),
                             'timedatectl': timeout})
        health = HostTimeHealth(runner).read()
        self.assertEqual('unknown', health['provider'])
        self.assertFalse(health['synced'])
        self.assertTrue(all(call[1]['timeout'] == 2 for call in runner.calls))

    def test_timesyncd_parse(self):
        output = ('ServerName=ntp.example.org\nServerAddress=192.0.2.1\nRootDistanceMaxUSec=5s\n'
                  'PollIntervalUSec=32s\nFrequency=0\nNTPMessage={ Leap=0, Stratum=3 }\n')
        runner = FakeRunner({'chronyc': (127, '', 'missing'),
                             'timedatectl': (0, output, '')})
        health = HostTimeHealth(runner).read()
        self.assertEqual('systemd-timesyncd', health['provider'])
        self.assertTrue(health['synced'])
        self.assertEqual(3, health['stratum'])
        self.assertEqual('ntp.example.org', health['reference'])


class TestTimeHealthTransform(unittest.TestCase):
    def transform(self, **kwargs):
        host = kwargs.pop('host_reader', lambda: {
            'provider': 'chrony', 'synced': True, 'offset_s': 0.01})
        return TimeHealthTransform(streams={
            'gps_a': {'source_time_field': 'utc', 'source': 'embedded'},
            'gps_b': {'source_time_field': 'utc', 'source': 'embedded'},
        }, host_reader=host, window=10, jump_s=5, **kwargs)

    @staticmethod
    def record(stream, arrival, source):
        return {'timestamp': arrival, 'fields': {'stream': stream, 'utc': source}}

    def test_latency_stats_and_preserves_values(self):
        transform = self.transform()
        base = datetime.datetime(2026, 1, 1, tzinfo=UTC)
        records = [self.record('gps_a',
                               (base + datetime.timedelta(seconds=i + latency)).timestamp(),
                               (base + datetime.timedelta(seconds=i)).isoformat())
                   for i, latency in enumerate([1, 2, 3, 4])]
        result = transform.transform(records)
        self.assertIs(result, records)
        self.assertEqual(2.5, result[-1]['fields']['ds_time:gps_a:latency_median_s'])
        self.assertAlmostEqual(3.85, result[-1]['fields']['ds_time:gps_a:latency_p95_s'])
        self.assertEqual('embedded', result[-1]['fields']['ds_time:gps_a:timestamp_source'])
        self.assertEqual('degraded', result[-1]['fields']['ds_time:gps_a:confidence'])

    def test_backward_repeat_and_jump(self):
        transform = self.transform()
        arrivals = [100, 101, 102, 103]
        sources = [100, 100, 90, 110]
        results = [transform.transform(self.record('gps_a', a, s))
                   for a, s in zip(arrivals, sources)]
        fields = results[-1]['fields']
        self.assertEqual(1, fields['ds_time:gps_a:repeats'])
        self.assertEqual(1, fields['ds_time:gps_a:backward_steps'])
        self.assertEqual(2, fields['ds_time:gps_a:jumps'])
        self.assertEqual('degraded', fields['ds_time:gps_a:confidence'])

    def test_midnight_time_of_day_uses_record_date(self):
        transform = self.transform()
        before = datetime.datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC)
        after = datetime.datetime(2026, 1, 2, 0, 0, 1, tzinfo=UTC)
        transform.transform(self.record('gps_a', before.timestamp(), '235959'))
        result = transform.transform(self.record('gps_a', after.timestamp(), '000001'))
        self.assertEqual(0, result['fields']['ds_time:gps_a:backward_steps'])
        self.assertEqual(0, result['fields']['ds_time:gps_a:latency_median_s'])

    def test_bad_confidence_for_host_offset(self):
        transform = self.transform(host_reader=lambda: {
            'provider': 'chrony', 'synced': True, 'offset_s': 0.6})
        result = transform.transform(self.record('gps_a', 100, 100))
        self.assertEqual('bad', result['fields']['ds_time:gps_a:confidence'])

    def test_skew_between_embedded_streams(self):
        transform = self.transform()
        transform.transform(self.record('gps_a', 100, 98))
        result = transform.transform(self.record('gps_b', 100, 97.5))
        self.assertEqual(0.5, result['fields']['ds_time:gps_a:gps_b:skew_median_s'])

    def test_none_passes_through(self):
        self.assertIsNone(self.transform().transform(None))

    def test_existing_values_are_not_changed(self):
        record = self.record('gps_a', 100, 99)
        record['fields']['ds_time:host:provider'] = 'upstream-value'
        result = self.transform().transform(record)
        self.assertEqual('upstream-value', result['fields']['ds_time:host:provider'])


if __name__ == '__main__':
    unittest.main()
