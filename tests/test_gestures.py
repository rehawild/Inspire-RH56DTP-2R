from inspire_rh56dtp_2r import gestures
from inspire_rh56dtp_2r.gestures import H


def test_plan_from_open_is_the_gesture():
    assert gestures.plan("fist", [1000] * 5 + [986]) == gestures.GESTURES["fist"]


def test_plan_lifts_thumb_out_first_when_across_palm():
    steps = gestures.plan("point", [0, 0, 0, 0, 600, 0])
    assert steps[:2] == gestures.THUMB_OUT
    assert steps[2:] == gestures.GESTURES["point"]


def test_plan_returns_copies():
    gestures.plan("open", [1000] * 6)[0][0] = 5
    assert gestures.GESTURES["open"][0][0] == 1000


def test_reached_ignores_held_dofs():
    assert gestures.reached([H, H, H, H, 600, H], [0, 0, 0, 0, 625, 0])
    assert not gestures.reached([H, H, H, H, 600, H], [0, 0, 0, 0, 700, 0])


def test_thumb_force_only_lowers_thumb_bend():
    assert gestures.gesture_forces(500, 300) == [500, 500, 500, 500, 300, 500]
    assert gestures.gesture_forces(200, 300) == [200] * 6
