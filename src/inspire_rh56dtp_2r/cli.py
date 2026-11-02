"""Command line tool: ``python -m inspire_rh56dtp_2r --help``."""
import argparse
import contextlib
import sys
import time

from . import gestures
from . import registers as R
from .hand import RH56Hand, decode_errors
from .modbus import ModbusError

DEFAULT_SPEED = 300
DEFAULT_FORCE = 500
H = R.HOLD
POSES = {
    # Thumb is left alone so it cannot collide with the closing fingers.
    "close": [0, 0, 0, 0, H, H],
}


def format_state(state):
    lines = [f"{'dof':13}{'angle':>6}{'target':>7}{'force g':>8}{'mA':>6}{'°C':>4}  status"]
    for i, name in enumerate(R.DOF_NAMES):
        status = R.STATUS_CODES.get(state.status[i], f"code {state.status[i]}")
        errors = decode_errors(state.error[i])
        if errors:
            status += "  ERROR: " + ", ".join(errors)
        target = "hold" if state.angle_set[i] == R.HOLD else state.angle_set[i]
        lines.append(f"{name:13}{state.angle[i]:6}{target:>7}{state.force[i]:8}"
                     f"{state.current[i]:6}{state.temperature[i]:4}  {status}")
    lines.append(f"speed set {list(state.speed_set)}   force limit {list(state.force_set)} g")
    return "\n".join(lines)


def format_tactile(frame, region=None):
    if region:
        return "\n".join(" ".join(f"{v:4}" for v in row) for row in frame[region])
    lines = [f"{'region':14}{'max':>5}{'sum':>8}  cells>50"]
    for name, rows in frame.items():
        cells = [v for row in rows for v in row]
        lines.append(f"{name:14}{max(cells):5}{sum(cells):8}  {sum(v > 50 for v in cells)}")
    return "\n".join(lines)


def cmd_status(hand, args):
    print(f"hand id {hand.read_hand_id()} at {hand.read_ip()}")
    print(format_state(hand.read_state()))


def cmd_watch(hand, args):
    _loop(args.rate, lambda: format_state(hand.read_state()))


def cmd_tactile(hand, args):
    show = lambda: format_tactile(hand.read_tactile(), args.region)
    if args.watch:
        _loop(args.rate, show)
    else:
        print(show())


def cmd_move(hand, args):
    if args.command == "move":
        target = args.angles
    else:
        target = POSES[args.command]
    _move(hand, target, args)


def cmd_gesture(hand, args):
    steps = gestures.plan(args.gesture, hand.read_state().angle)
    forces = gestures.gesture_forces(args.force, args.thumb_force)
    for i, step in enumerate(steps):
        _move(hand, step, args, forces=forces, report=i == len(steps) - 1)


def cmd_gui(hand, args):
    from .gui import run
    run(hand, args)


def cmd_demo(hand, args):
    """Move one DOF at a time halfway closed and back open."""
    _move(hand, gestures.GESTURES["open"][0], args)
    for i, name in enumerate(R.DOF_NAMES):
        print(f"-- {name}")
        half = [R.HOLD] * R.N_DOF
        half[i] = 500
        _move(hand, half, args)
        half[i] = 1000
        _move(hand, half, args)


def cmd_hold(hand, args):
    state = hand.hold()
    print(f"holding at {list(state.angle)}")


def cmd_clear_errors(hand, args):
    hand.clear_errors()
    time.sleep(0.1)
    faults = hand.read_state().faults
    print(f"still reporting: {faults}" if faults else "no errors reported")


def _move(hand, target, args, forces=None, report=True):
    state = hand.read_state()
    if state.faults:
        raise SystemExit(f"refusing to move, hand reports {state.faults}; "
                         "check the hand, then run clear-errors")
    hand.set_speeds([args.speed] * R.N_DOF)
    hand.set_forces(forces or [args.force] * R.N_DOF)
    hand.set_angles(target)
    if args.no_wait:
        return
    try:
        state = hand.wait_until_settled(timeout=args.timeout)
    except KeyboardInterrupt:
        state = hand.hold()
        print("\ninterrupted: holding current position")
        print(format_state(state))
        raise SystemExit(130)
    if report:
        print(format_state(state))
    if state.faults:
        raise SystemExit(f"hand reported {state.faults}")


def _loop(rate, render):
    try:
        while True:
            text = render()
            sys.stdout.write("\x1b[H\x1b[J" + text + "\n\n(Ctrl+C to quit)\n")
            sys.stdout.flush()
            time.sleep(1.0 / rate)
    except KeyboardInterrupt:
        print()


def build_parser():
    p = argparse.ArgumentParser(prog="rh56", description="Inspire RH56DTP-2R hand over Ethernet")
    p.add_argument("--ip", default=R.DEFAULT_IP)
    p.add_argument("--port", type=int, default=R.DEFAULT_PORT)
    p.add_argument("--sim", action="store_true", help="use a built-in simulated hand")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("status", help="read state once (default)").set_defaults(func=cmd_status)

    s = sub.add_parser("watch", help="live state view")
    s.add_argument("--rate", type=float, default=10.0)
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("tactile", help="tactile sensor summary or one region's cells")
    s.add_argument("--region", choices=[r[0] for r in R.TACTILE_REGIONS])
    s.add_argument("--watch", action="store_true")
    s.add_argument("--rate", type=float, default=10.0)
    s.set_defaults(func=cmd_tactile)

    motion = argparse.ArgumentParser(add_help=False)
    motion.add_argument("--speed", type=int, default=DEFAULT_SPEED, help="0..1000")
    motion.add_argument("--force", type=int, default=DEFAULT_FORCE, help="force limit, 0..3000 g")
    motion.add_argument("--timeout", type=float, default=5.0, help="seconds to wait for motion")
    motion.add_argument("--no-wait", action="store_true")

    gesture_help = {
        "open": "open all DOFs (thumb first if it is across the palm)",
        "fist": "fingers, then thumb across and over",
        "point": "index out, the rest in a fist",
        "thumbs up": "fingers closed, thumb out",
    }
    for name, text in gesture_help.items():
        s = sub.add_parser(name.replace(" ", "-"), parents=[motion], help=text)
        s.add_argument("--thumb-force", type=int, default=gestures.FIST_THUMB_FORCE,
                       help="force limit for thumb bend, g")
        s.set_defaults(func=cmd_gesture, gesture=name)
    sub.add_parser("close", parents=[motion],
                   help="close the four fingers, thumb untouched").set_defaults(func=cmd_move)
    s = sub.add_parser("move", parents=[motion], help="move to six raw angles")
    s.add_argument("angles", type=int, nargs=R.N_DOF, metavar="A",
                   help=f"0..1000 (1000 = open) or -1 to hold; order: {' '.join(R.DOF_NAMES)}")
    s.set_defaults(func=cmd_move)
    sub.add_parser("demo", parents=[motion],
                   help="each DOF halfway and back, one at a time").set_defaults(func=cmd_demo)

    s = sub.add_parser("gui", help="control panel with live feedback and tactile view")
    s.add_argument("--rate", type=float, default=20.0, help="feedback updates per second")
    s.set_defaults(func=cmd_gui)

    sub.add_parser("hold", help="stay at the measured position").set_defaults(func=cmd_hold)
    sub.add_parser("clear-errors", help="clear clearable actuator errors").set_defaults(
        func=cmd_clear_errors)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", cmd_status)
    with contextlib.ExitStack() as stack:
        if args.sim:
            from .sim import SimServer
            args.ip, args.port = stack.enter_context(SimServer()).address
        try:
            hand = stack.enter_context(RH56Hand(args.ip, args.port))
            func(hand, args)
        except (OSError, ModbusError) as e:
            raise SystemExit(f"cannot talk to the hand at {args.ip}:{args.port}: {e}\n"
                             "Is it powered, and does this PC have an address on its subnet? "
                             "See scripts/setup-network.sh")
        except ValueError as e:
            raise SystemExit(f"invalid command: {e}")


if __name__ == "__main__":
    main()
