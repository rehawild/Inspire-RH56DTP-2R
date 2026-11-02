import socket
import socketserver
import struct
import threading

import pytest

from inspire_rh56dtp_2r.modbus import ModbusError, ModbusTCPClient, read_request, to_signed, write_request


def test_read_request_frame():
    assert read_request(1, 0xFF, 1546, 6).hex() == "000100000006ff03060a0006"


def test_write_request_encodes_negative_values():
    frame = write_request(2, 1, 1486, [1000, -1])
    assert frame.hex() == "00020000000b01" + "10" + "05ce" + "0002" + "04" + "03e8" + "ffff"


def test_to_signed():
    assert to_signed(0xFFFF) == -1
    assert to_signed(1000) == 1000


def test_read_write_roundtrip(sim):
    with ModbusTCPClient(*sim.address) as client:
        client.write_registers(1498, [111, 222])
        assert client.read_registers(1498, 2) == [111, 222]


def test_exception_response_raises_and_client_recovers(sim):
    with ModbusTCPClient(*sim.address, reconnect_delay=0) as client:
        with pytest.raises(ModbusError):
            client._transact(lambda tx: struct.pack(">HHHBB", tx, 0, 2, 1, 0x2B))
        assert client.read_registers(1000, 1) == [1]


def test_count_is_validated(sim):
    with ModbusTCPClient(*sim.address) as client:
        with pytest.raises(ValueError):
            client.read_registers(3000, 126)


class _WrongTxIdHandler(socketserver.BaseRequestHandler):
    """Answers every read with the transaction ID off by one, like some hand firmware."""

    def handle(self):
        while True:
            req = self.request.recv(12)
            if len(req) < 12:
                return
            tx_id, _, _, unit, fn, _, count = struct.unpack(">HHHBBHH", req)
            body = bytes([fn, 2 * count]) + b"\x00\x2a" * count
            self.request.sendall(struct.pack(">HHHB", tx_id + 1, 0, len(body) + 1, unit) + body)


def test_tolerates_wrong_transaction_id():
    server = socketserver.TCPServer(("127.0.0.1", 0), _WrongTxIdHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with ModbusTCPClient(*server.server_address) as client:
            assert client.read_registers(1546, 3) == [42, 42, 42]
            assert client.read_registers(1546, 1) == [42]
    finally:
        server.shutdown()
        server.server_close()


def test_connection_refused_raises_oserror():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(OSError):
        ModbusTCPClient("127.0.0.1", port, timeout=0.5).read_registers(1000, 1)
