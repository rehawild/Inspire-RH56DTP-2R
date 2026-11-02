#!/usr/bin/env python3
"""Interactive tactile check: press each sensor region while this records.

    PYTHONPATH=src python3 scripts/tactile_check.py [--seconds 45] [--ip ...]

Records a baseline with nothing touching the hand, then reports for every
region the peak rise above baseline, how long it was pressed and when it was
first touched. Regions that never rose above --threshold are listed as untouched.
"""
import argparse
import time

from inspire_rh56dtp_2r import DEFAULT_IP, RH56Hand


def flat(frame):
    return {name: [v for row in rows for v in row] for name, rows in frame.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ip", default=DEFAULT_IP)
    p.add_argument("--seconds", type=float, default=45)
    p.add_argument("--baseline", type=float, default=2)
    p.add_argument("--threshold", type=int, default=150, help="rise counted as a touch")
    args = p.parse_args()

    with RH56Hand(args.ip) as hand:
        print(f"baseline for {args.baseline:.0f} s: don't touch the hand", flush=True)
        samples = []
        end = time.monotonic() + args.baseline
        while time.monotonic() < end:
            samples.append(flat(hand.read_tactile()))
        base = {name: [max(s[name][i] for s in samples) for i in range(len(cells))]
                for name, cells in samples[0].items()}

        print(f"recording {args.seconds:.0f} s: press each region now", flush=True)
        peak = {name: 0 for name in base}
        active = {name: 0.0 for name in base}
        first = {}
        start = last = time.monotonic()
        frames = 0
        while last - start < args.seconds:
            frame = flat(hand.read_tactile())
            now = time.monotonic()
            frames += 1
            for name, cells in frame.items():
                rise = max(v - b for v, b in zip(cells, base[name]))
                peak[name] = max(peak[name], rise)
                if rise >= args.threshold:
                    active[name] += now - last
                    if name not in first:
                        first[name] = now - start
                        print(f"  {now - start:5.1f} s  touched {name} (+{rise})", flush=True)
            last = now

    print(f"\n{frames} frames, {frames / args.seconds:.0f} Hz")
    print(f"{'region':14}{'base max':>9}{'peak rise':>10}{'pressed s':>10}{'first s':>8}")
    for name in base:
        mark = "" if name in first else "   <- not touched"
        when = f"{first[name]:8.1f}" if name in first else f"{'-':>8}"
        print(f"{name:14}{max(base[name]):9}{peak[name]:10}{active[name]:10.1f}{when}{mark}")


if __name__ == "__main__":
    main()
