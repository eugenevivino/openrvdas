import contextlib
import io
import logging
from pathlib import Path
import tempfile
import unittest

import yaml

from contrib.deepsignal.met_reports.report_writer import ReportWriter, TemplateError
from contrib.deepsignal.met_reports.verify import verify


class ReportWriterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def template(self, name='toy.yaml', **updates):
        data = {
            'name': 'toy', 'status': 'VERIFIED', 'period': 'hourly',
            'filename': '{ship}_{yyyymmdd}_{hh}.txt', 'header': ['REPORT'],
            'row': '{timestamp} {temperature:.1f} {course:03.0f} {note}',
            'missing': {'temperature': 'M', 'course': '/', 'note': 'NA'},
            'fields': ['timestamp', 'temperature', 'course', 'note'],
        }
        data.update(updates)
        path = self.root / name
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
        return path

    def test_toy_template_format_missing_filename_and_hour_boundary(self):
        writer = ReportWriter(self.template(), self.root / 'out', ship='KAOU')
        writer.write([
            {'timestamp': '2026-11-18T23:59:00Z',
             'fields': {'temperature': 12.05, 'course': 7, 'note': 'ok'}},
            {'timestamp': '2026-11-19T00:00:00Z',
             'fields': {'temperature': None}},
        ])
        writer.close()
        first = self.root / 'out/KAOU_20261118_23.txt'
        second = self.root / 'out/KAOU_20261119_00.txt'
        self.assertEqual(first.read_text(), 'REPORT\n2026-11-18T23:59:00Z 12.1 007 ok\n')
        self.assertEqual(second.read_text(), 'REPORT\n2026-11-19T00:00:00Z M / NA\n')

    def test_daily_boundary_uses_record_time_and_none_passes_through(self):
        writer = ReportWriter(self.template(
            period='daily', filename='{ship}_{yyyymmdd}.txt'),
                              self.root / 'daily', ship='KAOU')
        self.assertIsNone(writer.write(None))
        writer.write({'timestamp': '2026-11-18T23:59:00Z', 'fields': {}})
        writer.write({'timestamp': '2026-11-19T00:00:00Z', 'fields': {}})
        writer.close()
        self.assertEqual(len(list((self.root / 'daily').glob('*.txt'))), 2)

    def test_bad_placeholder_fails_at_load_with_plain_message(self):
        path = self.template(row='{not_declared}')
        with self.assertRaisesRegex(TemplateError,
                                    "setting 'row'.*not_declared.*missing"):
            ReportWriter(path, self.root / 'out', ship='KAOU')

    def test_unverified_template_warns_once(self):
        with self.assertLogs(level=logging.WARNING) as caught:
            writer = ReportWriter(self.template(status='UNVERIFIED'),
                                  self.root / 'out', ship='KAOU')
            writer.write(None)
            writer.close()
        self.assertEqual(len(caught.records), 1)
        self.assertIn('UNVERIFIED', caught.output[0])

    def test_samos_template_reproduces_real_sample_byte_for_byte(self):
        package = Path('contrib/deepsignal/met_reports/templates')
        sample = Path('contrib/deepsignal/test/met_reports/samos_sample.txt')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = verify(package / 'samos_daily.yaml', sample)
        self.assertEqual(result, 0)
        self.assertIn('exact match', output.getvalue())

    def test_verify_reports_one_byte_difference(self):
        path = self.template(row='{value}', fields=['value'], missing={'value': ''},
                             parse={'pattern': r'^(?P<value>.*)$'})
        sample = self.root / 'sample.txt'
        sample.write_bytes(b'A\n')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = verify(path, sample, rendered_override=b'B\n')
        self.assertEqual(result, 1)
        self.assertIn('-A', output.getvalue())
        self.assertIn('+B', output.getvalue())


if __name__ == '__main__':
    unittest.main()
