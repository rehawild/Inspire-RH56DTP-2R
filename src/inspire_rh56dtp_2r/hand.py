"""High-level interface to an Inspire RH56DTP/RH56DFTP hand over Modbus TCP."""
import math
import struct
import time
from dataclasses import dataclass

from . import registers as R
from .modbus import MAX_READ_REGS, ModbusTCPClient


def registers_to_bytes(regs):
    """Undo the hand's register packing: back to its little-endian memory bytes."""
    return struct.pack(f"<{len(regs)}H", *regs)


def _int16s(mem, offset, n=R.N_DOF):
    return struct.unpack_from(f"<{n}h", mem, offset)


def _bytes(mem, offset, n=R.N_DOF):
    return tuple(mem[offset:offset + n])


def decode_errors(code):
    return [name for bit, name in R.ERROR_BITS.items() if code & (1 << bit)]


@dataclass(frozen=True)
class HandState:
    angle_set: tuple
    force_set: tuple
    speed_set: tuple
    position: tuple
    angle: tuple
    force: tuple
    current: tuple
    error: tuple
    status: tuple
    temperature: tuple

    @classmethod
    def from_registers(cls, regs):
        mem = registers_to_bytes(regs)
        at = lambda addr: addr - R.STATE_START
        return cls(
            angle_set=_int16s(mem, at(R.ANGLE_SET)),
            force_set=_int16s(mem, at(R.FORCE_SET)),
            speed_set=_int16s(mem, at(R.SPEED_SET)),
            position=_int16s(mem, at(R.POS_ACT)),
            angle=_int16s(mem, at(R.ANGLE_ACT)),
            force=_int16s(mem, at(R.FORCE_ACT)),
            current=_int16s(mem, at(R.CURRENT)),
            error=_bytes(mem, at(R.ERROR)),
            status=_bytes(mem, at(R.STATUS)),
            temperature=_bytes(mem, at(R.TEMP)),
        )

    @property
    def faults(self):
        """{dof name: [error descriptions]} for every DOF reporting an error."""
        return {name: decode_errors(code)
                for name, code in zip(R.DOF_NAMES, self.error) if code}


def normalize_command(values, valid_range, allow_hold):
    """Validate a 6-DOF command given as a sequence or a {dof name: value} dict.

    Missing dict entries mean "hold" when allowed. Returns a list of 6 ints.
    """
    if isinstance(values, dict):
        unknown = set(values) - set(R.DOF_NAMES)
        if unknown:
            raise ValueError(f"unknown DOF names {sorted(unknown)}; expected {R.DOF_NAMES}")
        if not allow_hold and len(values) != R.N_DOF:
            raise ValueError(f"all six DOFs are required: {R.DOF_NAMES}")
        values = [values.get(name, R.HOLD) for name in R.DOF_NAMES]
    values = list(values)
    if len(values) != R.N_DOF:
        raise ValueError(f"expected {R.N_DOF} values, got {len(values)}")
    lo, hi = valid_range
    out = []
    for name, v in zip(R.DOF_NAMES, values):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{name}: {v!r} is not a finite number")
        v = int(round(v))
        if allow_hold and v == R.HOLD:
            out.append(v)
        elif lo <= v <= hi:
            out.append(v)
        else:
            hold = f" or {R.HOLD} to hold" if allow_hold else ""
            raise ValueError(f"{name}: {v} is outside {lo}..{hi}{hold}")
    return out


class RH56Hand:
    """Connecting and reading never move the hand; only the set_*/hold calls write."""

    def __init__(self, ip=R.DEFAULT_IP, port=R.DEFAULT_PORT, unit=1, timeout=1.0, client=None):
        self.client = client or ModbusTCPClient(ip, port, unit=unit, timeout=timeout)

    def connect(self):
        self.client.connect()
        return self

    def close(self):
        self.client.close()

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # -- reading -----------------------------------------------------------

    def read_state(self):
        return HandState.from_registers(
            self.client.read_registers(R.STATE_START, R.STATE_REGS))

    def read_hand_id(self):
        return self.client.read_registers(R.HAND_ID, 1)[0] & 0xFF

    def read_ip(self):
        regs = self.client.read_registers(R.IP_PART1, 2)
        return ".".join(str(b) for b in registers_to_bytes(regs))

    def read_tactile(self):
        """{region name: rows of 0..4095 values}, oriented as in the manual's figure."""
        regs = []
        addr = R.TACTILE_START
        while addr < R.TACTILE_END:
            count = min(MAX_READ_REGS, (R.TACTILE_END - addr) // 2)
            regs += self.client.read_registers(addr, count)
            addr += 2 * count
        mem = registers_to_bytes(regs)
        out = {}
        for name, start, rows, cols in R.TACTILE_REGIONS:
            cells = struct.unpack_from(f"<{rows * cols}H", mem, start - R.TACTILE_START)
            if name == "palm":
                # Column-major, each column listed from the bottom row up.
                out[name] = [[cells[c * rows + (rows - 1 - r)] for c in range(cols)]
                             for r in range(rows)]
            else:
                out[name] = [list(cells[r * cols:(r + 1) * cols]) for r in range(rows)]
        return out

    # -- commanding --------------------------------------------------------

    def set_angles(self, angles):
        """0..1000 per DOF (1000 = open), -1 leaves a DOF where it is."""
        self._write(R.ANGLE_SET, normalize_command(angles, R.ANGLE_RANGE, allow_hold=True))

    def set_speeds(self, speeds):
        """0..1000 per DOF; 1000 is a full stroke in about 0.6 s without load."""
        self._write(R.SPEED_SET, normalize_command(speeds, R.SPEED_RANGE, allow_hold=False))

    def set_forces(self, forces):
        """Force limit in grams at the fingertip, 0..3000 per DOF."""
        self._write(R.FORCE_SET, normalize_command(forces, R.FORCE_RANGE, allow_hold=False))

    def hold(self):
        """Command every DOF to stay at its measured angle. Not an emergency stop."""
        state = self.read_state()
        self._write(R.ANGLE_SET, list(state.angle))
        return state

    def clear_errors(self):
        # Register 1004 spans CLEAR_ERROR (low byte) and SAVE (high byte, kept 0).
        self.client.write_registers(R.CLEAR_ERROR, [1])

    def wait_until_settled(self, timeout=3.0, poll=0.05, still_for=0.25, tolerance=2):
        """Poll until the measured angles stop changing; returns the final state."""
        deadline = time.monotonic() + timeout
        state = self.read_state()
        still_since = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(poll)
            new = self.read_state()
            if max(abs(a - b) for a, b in zip(new.angle, state.angle)) > tolerance:
                still_since = time.monotonic()
            state = new
            if time.monotonic() - still_since >= still_for:
                break
        return state

    def _write(self, address, values):
        self.client.write_registers(address, [v & 0xFFFF for v in values])
