"""Minimal Modbus TCP client (function codes 03, 06 and 16), stdlib only.

Written for the Inspire hand's quirks:
- Every write is answered and the answer must be read, otherwise the hand's
  send buffer fills up and it stops responding.
- Some firmware echoes the wrong transaction ID, so responses are matched by
  order (one request in flight at a time) rather than by ID.
"""
import socket
import struct
import threading
import time

READ_HOLDING = 0x03
WRITE_SINGLE = 0x06
WRITE_MULTIPLE = 0x10
MAX_READ_REGS = 125
MAX_WRITE_REGS = 123


class ModbusError(Exception):
    """The device answered with a Modbus exception response."""


def build_request(tx_id, unit, function, payload):
    return struct.pack(">HHHBB", tx_id, 0, len(payload) + 2, unit, function) + payload


def read_request(tx_id, unit, address, count):
    return build_request(tx_id, unit, READ_HOLDING, struct.pack(">HH", address, count))


def write_request(tx_id, unit, address, values):
    data = b"".join(struct.pack(">H", v & 0xFFFF) for v in values)
    payload = struct.pack(">HHB", address, len(values), len(data)) + data
    return build_request(tx_id, unit, WRITE_MULTIPLE, payload)


def to_signed(value):
    return value - 0x10000 if value & 0x8000 else value


class ModbusTCPClient:
    def __init__(self, host, port=502, unit=1, timeout=1.0, reconnect_delay=0.3):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self.reconnect_delay = reconnect_delay
        self._sock = None
        self._tx_id = 0
        self._lock = threading.Lock()
        self._closed_at = 0.0

    def connect(self):
        with self._lock:
            self._connect()

    def _connect(self):
        if self._sock is not None:
            return
        wait = self._closed_at + self.reconnect_delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)  # the hand needs a moment to release its TCP slot
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock

    def close(self):
        with self._lock:
            self._drop()

    def _drop(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            self._closed_at = time.monotonic()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def read_registers(self, address, count):
        """Read `count` holding registers; returns unsigned 16-bit ints."""
        if not 1 <= count <= MAX_READ_REGS:
            raise ValueError(f"count must be 1..{MAX_READ_REGS}, got {count}")
        data = self._transact(lambda tx: read_request(tx, self.unit, address, count))
        if len(data) != 1 + 2 * count or data[0] != 2 * count:
            raise ModbusError(f"bad read response length {len(data)} for {count} registers")
        return list(struct.unpack(f">{count}H", data[1:]))

    def write_registers(self, address, values):
        values = list(values)
        if not 1 <= len(values) <= MAX_WRITE_REGS:
            raise ValueError(f"can write 1..{MAX_WRITE_REGS} registers, got {len(values)}")
        self._transact(lambda tx: write_request(tx, self.unit, address, values))

    def _transact(self, make_frame):
        """Send one request; return the response PDU without its function code."""
        with self._lock:
            try:
                self._connect()
                self._tx_id = self._tx_id % 0xFFFF + 1
                frame = make_frame(self._tx_id)
                function = frame[7]
                self._discard_pending()
                self._sock.sendall(frame)
                header = self._recv_exact(7)
                _, protocol, length, _ = struct.unpack(">HHHB", header)
                if protocol != 0 or not 2 <= length <= 260:
                    raise ModbusError(f"malformed MBAP header {header.hex()}")
                pdu = self._recv_exact(length - 1)
            except (OSError, ModbusError):
                self._drop()
                raise
        if pdu[0] == function | 0x80:
            raise ModbusError(f"exception code {pdu[1]} for function {function:#04x}")
        if pdu[0] != function:
            raise ModbusError(f"expected function {function:#04x}, got {pdu[0]:#04x}")
        return pdu[1:]

    def _discard_pending(self):
        # A late answer to an earlier timed-out request would otherwise be
        # mistaken for the answer to this one.
        self._sock.setblocking(False)
        try:
            while True:
                try:
                    if not self._sock.recv(4096):
                        raise ConnectionError("connection closed by device")
                except BlockingIOError:
                    break
        finally:
            self._sock.settimeout(self.timeout)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("connection closed by device")
            buf += chunk
        return buf
