import math
import struct

import pytest

from inspire_rh56dtp_2r import registers as R
from inspire_rh56dtp_2r.hand import HandState, decode_errors, normalize_command, registers_to_bytes


def test_byte_arrays_unpack_low_byte_first():
    # As read from the real hand: TEMP registers carrying 24..29 deg C.
    regs = [24 | 25 << 8, 26 | 27 << 8, 28 | 29 << 8]
    assert list(registers_to_bytes(regs)) == [24, 25, 26, 27, 28, 29]


def test_state_decodes_every_block():
    mem = bytearray(2 * R.STATE_REGS)
    put = lambda addr, fmt, vals: struct.pack_into(fmt, mem, addr - R.STATE_START, *vals)
    put(R.ANGLE_SET, "<6h", [1000, 1000, 1000, 1000, -1, -1])
    put(R.ANGLE_ACT, "<6h", [1000, 900, 800, 700, 600, 500])
    put(R.FORCE_ACT, "<6h", [-5, 0, 10, 20, 30, 40])
    put(R.ERROR, "<6B", [0, 0, 0, 0b110, 0, 0])
    put(R.TEMP, "<6B", [24, 25, 26, 27, 28, 29])
    regs = list(struct.unpack(f"<{R.STATE_REGS}H", mem))
    state = HandState.from_registers(regs)
    assert state.angle_set == (1000, 1000, 1000, 1000, -1, -1)
    assert state.angle == (1000, 900, 800, 700, 600, 500)
    assert state.force[0] == -5
    assert state.temperature == (24, 25, 26, 27, 28, 29)
    assert state.faults == {"index": ["over temperature", "overcurrent"]}


def test_decode_errors_matches_manual_example():
    assert decode_errors(0x06) == ["over temperature", "overcurrent"]
    assert decode_errors(0) == []


@pytest.mark.parametrize("bad", [
    [0] * 5,
    [0, 0, 0, 0, 0, 1001],
    [0, 0, 0, 0, 0, -2],
    [0, 0, 0, 0, 0, math.nan],
    [0, 0, 0, 0, 0, math.inf],
    [0, 0, 0, 0, 0, True],
    [0, 0, 0, 0, 0, "500"],
    {"pinky": 0},
])
def test_invalid_angles_rejected(bad):
    with pytest.raises(ValueError):
        normalize_command(bad, R.ANGLE_RANGE, allow_hold=True)


def test_dict_command_holds_missing_dofs():
    assert normalize_command({"index": 0, "thumb_rotate": 250.4}, R.ANGLE_RANGE, True) == \
        [-1, -1, -1, 0, -1, 250]


def test_hold_not_allowed_for_speed():
    with pytest.raises(ValueError):
        normalize_command([-1] * 6, R.SPEED_RANGE, allow_hold=False)
    with pytest.raises(ValueError):
        normalize_command({"index": 100}, R.SPEED_RANGE, allow_hold=False)


def test_initial_state(hand):
    state = hand.read_state()
    assert state.angle == (1000,) * 6
    assert state.angle_set == (-1,) * 6
    assert state.faults == {}
    assert hand.read_hand_id() == 1
    assert hand.read_ip() == "192.168.11.210"


def test_move_and_settle(hand):
    hand.set_speeds([1000] * 6)
    hand.set_angles([0, 200, 400, 600, -1, 1000])
    state = hand.wait_until_settled(timeout=3)
    assert state.angle == (0, 200, 400, 600, 1000, 1000)
    assert state.angle_set == (0, 200, 400, 600, -1, 1000)
    assert state.status[:4] == (2, 2, 2, 2)


def test_speed_limits_motion(hand):
    hand.set_speeds([100] * 6)        # full stroke takes 6 s
    hand.set_angles({"index": 0})
    state = hand.wait_until_settled(timeout=0.3, still_for=1)
    assert 700 < state.angle[3] < 1000


def test_hold_freezes_mid_motion(hand):
    hand.set_speeds([200] * 6)
    hand.set_angles([0] * 6)
    hand.wait_until_settled(timeout=0.3, still_for=1)
    held = hand.hold()
    after = hand.wait_until_settled(timeout=2)
    assert all(abs(a - b) <= 3 for a, b in zip(after.angle, held.angle))
    assert all(0 < a < 1000 for a in after.angle)


def test_settings_roundtrip(hand):
    hand.set_speeds([100, 200, 300, 400, 500, 600])
    hand.set_forces([0, 500, 1000, 1500, 2000, 3000])
    state = hand.read_state()
    assert state.speed_set == (100, 200, 300, 400, 500, 600)
    assert state.force_set == (0, 500, 1000, 1500, 2000, 3000)


def test_clear_errors(hand, sim):
    sim.hand.inject_error(3, 0b101)
    assert hand.read_state().faults == {"index": ["locked rotor", "overcurrent"]}
    hand.clear_errors()
    assert hand.read_state().faults == {}
    assert sim.hand.mem[R.SAVE] == 0


def test_tactile_layout(hand, sim):
    finger = [[r * 8 + c for c in range(8)] for r in range(10)]
    palm = [[r * 14 + c for c in range(14)] for r in range(8)]
    sim.hand.set_tactile("index_pad", finger)
    sim.hand.set_tactile("palm", palm)
    frame = hand.read_tactile()
    assert len(frame) == 17
    assert frame["index_pad"] == finger
    assert frame["palm"] == palm
    assert frame["thumb_middle"] == [[0] * 3] * 3
    # Palm cell 1 in the manual is row 8, column 1.
    assert sim.hand.mem[4900] == palm[7][0]
