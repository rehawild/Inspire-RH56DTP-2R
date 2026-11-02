"""Tests against the real hand. Read-only unless RH56_ALLOW_MOTION=1.

    RH56_IP=192.168.11.210 python3 -m pytest tests/test_hardware.py -v
    RH56_IP=192.168.11.210 RH56_ALLOW_MOTION=1 python3 -m pytest tests/test_hardware.py -v
"""
import os

import pytest

from inspire_rh56dtp_2r import registers as R
from inspire_rh56dtp_2r.hand import RH56Hand

IP = os.environ.get("RH56_IP")
pytestmark = [pytest.mark.hardware,
              pytest.mark.skipif(not IP, reason="set RH56_IP to test the real hand")]
motion = pytest.mark.skipif(os.environ.get("RH56_ALLOW_MOTION") != "1",
                            reason="set RH56_ALLOW_MOTION=1 to move the real hand")


@pytest.fixture(scope="module")
def real_hand():
    with RH56Hand(IP) as hand:
        yield hand


def test_identity(real_hand):
    assert 1 <= real_hand.read_hand_id() <= 254
    assert real_hand.read_ip() == IP


def test_state_is_sane(real_hand):
    state = real_hand.read_state()
    assert state.faults == {}
    assert all(0 <= a <= 1000 for a in state.angle)
    assert all(0 <= p <= 2000 for p in state.position)
    assert all(10 <= t <= 70 for t in state.temperature)
    assert all(0 <= s <= 1000 for s in state.speed_set)
    assert all(0 <= f <= 3000 for f in state.force_set)


def test_tactile_frame(real_hand):
    frame = real_hand.read_tactile()
    assert len(frame) == len(R.TACTILE_REGIONS)
    assert all(0 <= v <= R.TACTILE_MAX for rows in frame.values() for row in rows for v in row)


@pytest.mark.motion
@motion
def test_index_half_and_back(real_hand):
    """Slowly moves only the index finger to 500 and back. Keep the hand clear."""
    assert real_hand.read_state().faults == {}
    real_hand.set_speeds([300] * 6)
    real_hand.set_forces([500] * 6)
    try:
        real_hand.set_angles({"index": 500})
        state = real_hand.wait_until_settled(timeout=4)
        assert abs(state.angle[3] - 500) <= 20, state
        assert state.faults == {}
    finally:
        real_hand.set_angles({"index": 1000})
    state = real_hand.wait_until_settled(timeout=4)
    assert state.angle[3] >= 980, state
