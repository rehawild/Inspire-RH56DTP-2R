"""In-process Modbus TCP server that behaves like an RH56 tactile hand.

It models register memory, angle targets with speed limits, -1 holds,
error clearing and a tactile frame. It does not model contact, force limits
or load. Run standalone with ``python -m inspire_rh56dtp_2r.sim``.
"""
import argparse
import socketserver
import struct
import threading
import time

from . import registers as R
from .modbus import READ_HOLDING, WRITE_MULTIPLE, WRITE_SINGLE

FULL_STROKE_S = 0.6       # speed 1000, no load (manual 2.6.13)
MEMORY_SIZE = 6000


class SimulatedHand:
    def __init__(self):
        self.mem = bytearray(MEMORY_SIZE)
        self.lock = threading.Lock()
        self._angle = [1000.0] * R.N_DOF
        self._set_u8(R.HAND_ID, [1])
        self._set_u8(R.IP_PART1, [192, 168, 11, 210])
        self._set_i16(R.ANGLE_SET, [R.HOLD] * R.N_DOF)
        self._set_i16(R.SPEED_SET, [1000] * R.N_DOF)
        self._set_i16(R.FORCE_SET, [1000] * R.N_DOF)
        self._set_u8(R.STATUS, [255] * R.N_DOF)
        self._set_u8(R.TEMP, [30] * R.N_DOF)
        self._sync_feedback()
        self._last = time.monotonic()

    # -- memory helpers (little-endian, byte addressed like the real hand) --

    def _set_i16(self, addr, values):
        struct.pack_into(f"<{len(values)}h", self.mem, addr, *values)

    def _get_i16(self, addr, n=R.N_DOF):
        return list(struct.unpack_from(f"<{n}h", self.mem, addr))

    def _set_u8(self, addr, values):
        self.mem[addr:addr + len(values)] = bytes(values)

    def read_registers(self, addr, count):
        with self.lock:
            self._advance()
            return list(struct.unpack_from(f"<{count}H", self.mem, addr))

    def write_registers(self, addr, values):
        with self.lock:
            self._advance()
            struct.pack_into(f"<{len(values)}H", self.mem, addr, *values)
            if addr <= R.CLEAR_ERROR < addr + 2 * len(values) and self.mem[R.CLEAR_ERROR]:
                self.mem[R.CLEAR_ERROR] = 0
                self._set_u8(R.ERROR, [0] * R.N_DOF)

    # -- test hooks --------------------------------------------------------

    def inject_error(self, dof, code):
        with self.lock:
            self.mem[R.ERROR + dof] = code

    def set_tactile(self, region, rows):
        """Write a region's cells in the manual's (row-major / palm column-major) order."""
        start, nrows, ncols = next((s, r, c) for n, s, r, c in R.TACTILE_REGIONS if n == region)
        if region == "palm":
            cells = [rows[nrows - 1 - r][c] for c in range(ncols) for r in range(nrows)]
        else:
            cells = [v for row in rows for v in row]
        with self.lock:
            struct.pack_into(f"<{len(cells)}H", self.mem, start, *cells)

    # -- motion model ------------------------------------------------------

    def _advance(self):
        now = time.monotonic()
        dt, self._last = now - self._last, now
        targets = self._get_i16(R.ANGLE_SET)
        speeds = self._get_i16(R.SPEED_SET)
        status = list(self.mem[R.STATUS:R.STATUS + R.N_DOF])
        for i, (target, speed) in enumerate(zip(targets, speeds)):
            if target == R.HOLD or self.mem[R.ERROR + i]:
                continue
            step = 1000.0 * dt * max(speed, 0) / (1000.0 * FULL_STROKE_S)
            delta = target - self._angle[i]
            if abs(delta) <= step:
                self._angle[i] = float(target)
                status[i] = 2
            else:
                self._angle[i] += step if delta > 0 else -step
                status[i] = 0 if delta > 0 else 1
        self._set_u8(R.STATUS, status)
        self._sync_feedback()

    def _sync_feedback(self):
        angles = [round(a) for a in self._angle]
        self._set_i16(R.ANGLE_ACT, angles)
        self._set_i16(R.POS_ACT, [2 * (1000 - a) for a in angles])


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        hand = self.server.hand
        sock = self.request
        while True:
            header = _recv_exact(sock, 7)
            if header is None:
                return
            tx_id, _, length, unit = struct.unpack(">HHHB", header)
            pdu = _recv_exact(sock, length - 1)
            if pdu is None:
                return
            sock.sendall(struct.pack(">HH", tx_id, 0) + _respond(hand, pdu, unit))


def _respond(hand, pdu, unit):
    """Length, unit ID and PDU of the reply (the MBAP header minus its first 4 bytes)."""
    function = pdu[0]
    try:
        if function == READ_HOLDING:
            addr, count = struct.unpack(">HH", pdu[1:5])
            regs = hand.read_registers(addr, count)
            body = struct.pack(">BB", function, 2 * count) + struct.pack(f">{count}H", *regs)
        elif function == WRITE_MULTIPLE:
            addr, count, _ = struct.unpack(">HHB", pdu[1:6])
            hand.write_registers(addr, struct.unpack(f">{count}H", pdu[6:6 + 2 * count]))
            body = struct.pack(">BHH", function, addr, count)
        elif function == WRITE_SINGLE:
            addr, value = struct.unpack(">HH", pdu[1:5])
            hand.write_registers(addr, [value])
            body = pdu[:5]
        else:
            body = bytes([function | 0x80, 1])
    except (struct.error, IndexError):
        body = bytes([function | 0x80, 2])
    return struct.pack(">HB", len(body) + 1, unit) + body


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class SimServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host="127.0.0.1", port=0, hand=None):
        super().__init__((host, port), _Handler)
        self.hand = hand or SimulatedHand()
        self._thread = None

    @property
    def address(self):
        return self.server_address[:2]

    def start(self):
        self._thread = threading.Thread(target=self.serve_forever, args=(0.05,), daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self.shutdown()
        self.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Simulated RH56 hand (Modbus TCP)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=R.DEFAULT_PORT)
    args = parser.parse_args(argv)
    with SimServer(args.host, args.port) as server:
        host, port = server.address
        print(f"simulated hand on {host}:{port}  (Ctrl+C to stop)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
