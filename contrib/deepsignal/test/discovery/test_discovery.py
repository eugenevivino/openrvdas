"""Tests for passive stream discovery."""

import json
import os
import tempfile
import unittest

from contrib.deepsignal.discovery.discovery import write_results
from contrib.deepsignal.discovery.serial_scan import scan_port
from contrib.deepsignal.discovery.udp_scan import scan_udp_port


NMEA = b"$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"


class FakeSerial:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False
        self.write_called = False

    def read(self, size=1):
        data, self.payload = self.payload[:size], self.payload[size:]
        return data

    def write(self, data):
        self.write_called = True
        raise AssertionError("discovery must never write")

    def close(self):
        self.closed = True


class SerialFactory:
    def __init__(self, busy=False, silent=False):
        self.busy = busy
        self.silent = silent
        self.instances = []

    def __call__(self, port, baudrate, timeout):
        if self.busy:
            raise OSError("resource busy")
        if self.silent:
            payload = b""
        elif baudrate == 4800:
            payload = NMEA * 3
        else:
            payload = b"\x00\xff\x01" * 30
        instance = FakeSerial(payload)
        self.instances.append(instance)
        return instance


class FakeSocket:
    def __init__(self, packets):
        self.packets = list(packets)
        self.closed = False

    def bind(self, address):
        self.address = address

    def settimeout(self, timeout):
        self.timeout = timeout

    def recvfrom(self, size):
        if not self.packets:
            raise TimeoutError()
        return self.packets.pop(0), ("127.0.0.1", 1234)

    def close(self):
        self.closed = True


class DiscoveryTest(unittest.TestCase):
    def test_serial_selects_nmea_baud_and_never_writes(self):
        factory = SerialFactory()
        result = scan_port("/dev/fake", listen_s=0.01, opener=factory,
                           baud_rates=[4800, 9600], clock=lambda: 0)
        self.assertEqual(4800, result["baud"])
        self.assertEqual(["GP"], result["nmea_talkers"])
        self.assertEqual(["GGA"], result["nmea_sentences"])
        self.assertTrue(all(item.closed for item in factory.instances))
        self.assertFalse(any(item.write_called for item in factory.instances))

    def test_silent_and_busy_ports_are_reported(self):
        silent = scan_port("/dev/silent", 0.01, SerialFactory(silent=True),
                           baud_rates=[4800], clock=lambda: 0)
        busy = scan_port("/dev/busy", 0.01, SerialFactory(busy=True),
                         baud_rates=[4800], clock=lambda: 0)
        self.assertEqual("silent: may need polling", silent["status"])
        self.assertEqual("busy: skipped", busy["status"])

    def test_udp_rate_capture_and_json_shape(self):
        sock = FakeSocket([b"one\n", b"two\n"])
        ticks = iter([0.0, 1.0])
        result = scan_udp_port(6221, listen_s=1, opener=lambda: sock,
                               clock=lambda: next(ticks))
        self.assertEqual(2.0, result["lines_per_second"])
        with tempfile.TemporaryDirectory() as directory:
            output = write_results([result], directory, capture_dir=directory)
            with open(output, encoding="utf-8") as source:
                saved = json.load(source)
            self.assertEqual("udp", saved["streams"][0]["transport"])
            self.assertEqual(6221, saved["streams"][0]["port"])
            capture = os.path.join(directory, "udp_6221.txt")
            self.assertTrue(os.path.exists(capture))
            with open(capture, encoding="utf-8") as source:
                self.assertEqual("one\ntwo\n", source.read())


if __name__ == "__main__":
    unittest.main()
