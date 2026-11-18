import os
import socket
import threading
import unittest

from contrib.deepsignal.scoreboard import contract
from contrib.deepsignal.scoreboard.contract import RegisterWrite, TransportError


RTU_REQUEST = bytes.fromhex('01 10 00 00 00 01 02 00 7B E6 73')
RTU_REPLY = bytes.fromhex('01 10 00 00 00 01 01 C9')
TCP_REQUEST = bytes.fromhex('00 01 00 00 00 09 01 10 00 00 00 01 02 00 7B')


class Server:
    def __init__(self, sock, handler):
        self.sock = sock
        self.error = None
        self.thread = threading.Thread(target=self._run, args=(handler,))
        self.thread.start()

    def _run(self, handler):
        try:
            handler(self.sock)
        except BaseException as error:
            self.error = error

    def finish(self):
        self.thread.join(3)
        if self.thread.is_alive():
            raise AssertionError('server thread did not finish')
        if self.error:
            raise self.error


class TransportTests(unittest.TestCase):
    def test_registry_and_type_mismatches(self):
        for name in contract.TRANSPORT_NAMES:
            cls = contract.transport_class(name)
            self.assertTrue(issubclass(cls, contract.Transport))
            if name == 'serial':
                transport = cls(port='/not/opened')
            elif name == 'rs485':
                transport = cls(port='/not/opened')
            elif name in ('tcp', 'udp'):
                transport = cls(host='127.0.0.1', port=9)
            elif name == 'modbus_rtu':
                transport = cls(port='/not/opened')
            else:
                transport = cls(host='127.0.0.1')
            wrong = [RegisterWrite(1, 0, [1])] if name in contract.BYTE_TRANSPORTS else [b'x']
            with self.assertRaises(TransportError):
                transport.send(wrong)

    def test_serial_pty_pacing_and_validation(self):
        from contrib.deepsignal.scoreboard.transports.serial import TRANSPORT
        master, slave = os.openpty()
        path = os.ttyname(slave)
        transport = TRANSPORT(port=path, inter_frame_delay=0.25)
        sleeps = []
        transport.sleep = sleeps.append
        try:
            transport.send([b'one', b'two'])
            self.assertEqual(os.read(master, 6), b'onetwo')
            self.assertEqual(sleeps, [0.25])
        finally:
            transport.close()
            transport.close()
            os.close(master)
            os.close(slave)
        for settings in ({'port': path, 'parity': 'X'}, {'port': path, 'mystery': 1}):
            with self.assertRaisesRegex(TransportError, 'parity|mystery'):
                TRANSPORT(**settings)

    def test_rs485_settings(self):
        from contrib.deepsignal.scoreboard.transports.rs485 import TRANSPORT

        class FakeSettings:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        transport = TRANSPORT(port='unused', rts_level_for_tx=False,
                              delay_before_tx=0.2, delay_before_rx=None)
        settings = transport._rs485_settings(FakeSettings)
        self.assertEqual(settings.kwargs, {
            'rts_level_for_tx': False, 'rts_level_for_rx': False,
            'delay_before_tx': 0.2, 'delay_before_rx': None,
            'loopback': False})

    def test_tcp_frames_and_refused(self):
        from contrib.deepsignal.scoreboard.transports.tcp import TRANSPORT
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        received = []

        def handle(sock):
            conn, _ = sock.accept()
            with conn:
                while sum(map(len, received)) < 6:
                    received.append(conn.recv(6))
            sock.close()

        server = Server(listener, handle)
        transport = TRANSPORT(host='127.0.0.1', port=listener.getsockname()[1])
        transport.send([b'one', b'two'])
        transport.close()
        server.finish()
        self.assertEqual(b''.join(received), b'onetwo')
        refused = socket.socket()
        refused.bind(('127.0.0.1', 0))
        port = refused.getsockname()[1]
        refused.close()
        with self.assertRaises(TransportError):
            TRANSPORT(host='127.0.0.1', port=port, connect_timeout=0.1).send([b'x'])

    def test_udp_one_datagram_per_frame(self):
        from contrib.deepsignal.scoreboard.transports.udp import TRANSPORT
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver.bind(('127.0.0.1', 0))
        receiver.settimeout(2)
        transport = TRANSPORT(host='127.0.0.1', port=receiver.getsockname()[1])
        transport.send([b'one', b'two'])
        self.assertEqual(receiver.recv(10), b'one')
        self.assertEqual(receiver.recv(10), b'two')
        transport.close()
        receiver.close()

    def _rtu_case(self, reply, error=False):
        from contrib.deepsignal.scoreboard.transports.modbus_rtu import TRANSPORT
        master, slave = os.openpty()
        path = os.ttyname(slave)

        def handle(_):
            request = os.read(master, len(RTU_REQUEST))
            self.assertEqual(request, RTU_REQUEST)
            if reply is not None:
                os.write(master, reply)

        server = Server(None, handle)
        transport = TRANSPORT(port=path, response_timeout=0.1)
        try:
            if error:
                with self.assertRaises(TransportError):
                    transport.send([RegisterWrite(1, 0, [123])])
            else:
                transport.send([RegisterWrite(1, 0, [123])])
        finally:
            transport.close()
            server.finish()
            os.close(master)
            os.close(slave)

    def test_modbus_rtu_golden_and_errors(self):
        self._rtu_case(RTU_REPLY)
        self._rtu_case(RTU_REPLY[:-1] + bytes([RTU_REPLY[-1] ^ 1]), True)
        body = bytes.fromhex('01 90 02')
        crc = contract.checksum(body, 'crc16_modbus').to_bytes(2, 'little')
        self._rtu_case(body + crc, True)
        self._rtu_case(None, True)

    def test_modbus_rtu_broadcast_and_value_validation(self):
        from contrib.deepsignal.scoreboard.transports.modbus_rtu import TRANSPORT
        master, slave = os.openpty()
        transport = TRANSPORT(port=os.ttyname(slave), response_timeout=0.05)
        try:
            transport.send([RegisterWrite(0, 0, [123])])
            self.assertEqual(os.read(master, len(RTU_REQUEST))[0], 0)
            for write in (RegisterWrite(1, 0, []), RegisterWrite(1, 0, [65536])):
                with self.assertRaises(TransportError):
                    transport.send([write])
        finally:
            transport.close()
            os.close(master)
            os.close(slave)

    def test_modbus_tcp_golden_and_transaction_increment(self):
        from contrib.deepsignal.scoreboard.transports.modbus_tcp import TRANSPORT
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()

        def recv_exact(conn, count):
            data = b''
            while len(data) < count:
                data += conn.recv(count - len(data))
            return data

        def handle(sock):
            conn, _ = sock.accept()
            with conn:
                for transaction in (1, 2):
                    request = recv_exact(conn, len(TCP_REQUEST))
                    expected = transaction.to_bytes(2, 'big') + TCP_REQUEST[2:]
                    self.assertEqual(request, expected)
                    response = (transaction.to_bytes(2, 'big') + bytes.fromhex(
                        '00 00 00 06 01 10 00 00 00 01'))
                    conn.sendall(response)
            sock.close()

        server = Server(listener, handle)
        transport = TRANSPORT(host='127.0.0.1', port=listener.getsockname()[1])
        transport.send([RegisterWrite(1, 0, [123]), RegisterWrite(1, 0, [123])])
        transport.close()
        server.finish()


if __name__ == '__main__':
    unittest.main()
