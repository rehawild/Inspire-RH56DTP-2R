import pytest

from inspire_rh56dtp_2r import cli, gestures


def run(capsys, *argv):
    cli.main(["--sim", *argv])
    return capsys.readouterr().out


def test_status(capsys):
    out = run(capsys, "status")
    assert "hand id 1" in out
    assert "thumb_rotate" in out


def test_move_waits_and_reports(capsys):
    out = run(capsys, "move", "0", "-1", "-1", "-1", "-1", "-1", "--speed", "1000")
    first = out.splitlines()[1].split()
    assert first[:3] == ["little", "0", "0"]


def test_invalid_angle_exits(capsys):
    with pytest.raises(SystemExit, match="invalid command"):
        cli.main(["--sim", "move", "2000", "0", "0", "0", "0", "0"])


def test_move_refused_when_faulted(hand, sim):
    sim.hand.inject_error(0, 1)
    args = cli.build_parser().parse_args(["open"])
    with pytest.raises(SystemExit, match="refusing to move"):
        cli._move(hand, [1000] * 6, args)
    assert hand.read_state().angle_set == (-1,) * 6


def test_tactile_summary(capsys):
    out = run(capsys, "tactile")
    assert "palm" in out and "thumb_middle" in out


def test_unreachable_hand_message():
    with pytest.raises(SystemExit, match="cannot talk to the hand"):
        cli.main(["--ip", "127.0.0.1", "--port", "1", "status"])


def _spy_targets(hand, monkeypatch):
    sent = []
    real = hand.set_angles
    monkeypatch.setattr(hand, "set_angles", lambda t: (sent.append(list(t)), real(t)))
    return sent


def gesture(hand, *argv):
    cli.cmd_gesture(hand, cli.build_parser().parse_args([*argv, "--speed", "1000"]))


def test_fist_stages_and_thumb_force_limit(hand, monkeypatch):
    sent = _spy_targets(hand, monkeypatch)
    gesture(hand, "fist")
    assert sent == gestures.GESTURES["fist"]
    state = hand.read_state()
    assert state.angle == (0, 0, 0, 0, 600, 0)
    assert state.force_set == (500, 500, 500, 500, gestures.FIST_THUMB_FORCE, 500)


def test_open_from_fist_moves_thumb_out_first(hand, monkeypatch):
    gesture(hand, "fist")
    sent = _spy_targets(hand, monkeypatch)
    gesture(hand, "open")
    assert sent == [[-1, -1, -1, -1, 1000, -1], [-1, -1, -1, -1, -1, 1000], [1000] * 6]
    assert hand.read_state().angle == (1000,) * 6


def test_thumbs_up_command_name(hand):
    gesture(hand, "thumbs-up")
    assert hand.read_state().angle == (0, 0, 0, 0, 1000, 1000)
