import os
import time

import pytest

from inspire_rh56dtp_2r import gestures
from inspire_rh56dtp_2r.gui import HandWorker, heat_color


def wait_for(cond, timeout=4.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def worker(hand):
    w = HandWorker(hand, rate=50)
    w.start()
    yield w
    w.stop()


def test_worker_publishes_state_and_tactile(worker):
    assert wait_for(lambda: worker.snapshot is not None)
    _, state, tactile, error = worker.snapshot
    assert error is None and state.angle == (1000,) * 6 and len(tactile) == 17


def test_worker_merges_slider_moves(worker, hand):
    worker.set_limits([1000] * 6, [500] * 6)
    worker.set_angles([500, -1, -1, -1, -1, -1])
    worker.set_angles([-1, -1, -1, 200, -1, -1])
    assert wait_for(lambda: hand.read_state().angle == (500, 1000, 1000, 200, 1000, 1000))


def test_worker_hold_discards_pending_moves(worker, hand):
    worker.set_limits([100] * 6, [500] * 6)
    worker.set_angles([0] * 6)
    time.sleep(0.3)
    worker.set_angles([1000] * 6)
    worker.hold()
    assert wait_for(lambda: hand.read_state().angle_set != (0,) * 6)
    held = hand.read_state().angle_set
    assert all(0 < a < 1000 for a in held)


def test_worker_reports_lost_connection(worker, sim, hand):
    assert wait_for(lambda: worker.snapshot is not None)
    sim.stop()
    hand.client.close()        # the stopped server leaves open connections alive
    assert wait_for(lambda: worker.snapshot[3] is not None)


def test_heat_color_endpoints():
    assert heat_color(0, 1000) == "#181a30"
    assert heat_color(5000, 1000) == "#e63c28"


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs a display")
def test_panel_runs_a_gesture_and_stop(worker, hand):
    import tkinter as tk
    from inspire_rh56dtp_2r.gui import HandPanel

    root = tk.Tk()
    try:
        panel = HandPanel(root, worker, "test")

        def pump(cond, timeout=6.0):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                root.update()
                if cond():
                    return True
                time.sleep(0.01)
            return False

        worker.set_limits([1000] * 6, [500] * 6)
        assert pump(lambda: panel.angles is not None and panel.synced)
        panel.speed.set(1000)
        panel._apply_limits()
        panel.gesture("fist")
        assert pump(lambda: panel.step is None)
        assert hand.read_state().angle == (0, 0, 0, 0, 600, 0)
        assert [v.get() for v in panel.targets] == [0, 0, 0, 0, 600, 0]

        panel.gesture("open")
        assert pump(lambda: panel.step is not None and panel.step[4] == 1000)
        panel.stop()
        assert panel.step is None and panel.sequence == []
        time.sleep(0.3)
        assert pump(lambda: panel.synced)
        assert hand.read_state().angle != (1000,) * 6     # stopped before finishing
    finally:
        root.destroy()
