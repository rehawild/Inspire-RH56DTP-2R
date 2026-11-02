"""Multi-stage gestures shared by the CLI and the GUI.

A gesture is a list of 6-DOF angle targets sent one after another, each once
the previous one has finished. Fingers close before the thumb swings across
the palm, and the thumb is lifted and swung out before anything else moves
when it starts across the palm, so the thumb and fingers don't catch.
"""
from . import registers as R

H = R.HOLD
THUMB_IN = 900                  # thumb_rotate below this: thumb is across the palm
FIST_THUMB_FORCE = 300          # g, force limit for thumb bend in gestures
REACHED_TOLERANCE = 30

# With the fingers closed and the thumb rotated in, the thumb first touches the
# index finger at thumb_bend ~800 (measured on the RH56DTP-2R). 600 gives a firm
# grip; the thumb force limit keeps it from grinding into the fingers.
GESTURES = {
    "open": [[1000] * R.N_DOF],
    "fist": [[0, 0, 0, 0, H, H], [H, H, H, H, H, 0], [H, H, H, H, 600, H]],
    "point": [[0, 0, 0, 1000, H, H], [H, H, H, H, H, 0], [H, H, H, H, 600, H]],
    "thumbs up": [[0, 0, 0, 0, 1000, 1000]],
}
THUMB_OUT = [[H, H, H, H, 1000, H], [H, H, H, H, H, 1000]]


def plan(name, angles):
    """Steps to perform gesture `name` from measured `angles`."""
    steps = GESTURES[name]
    if angles[5] < THUMB_IN:
        steps = THUMB_OUT + steps
    return [list(step) for step in steps]


def reached(step, angles, tolerance=REACHED_TOLERANCE):
    return all(t == H or abs(a - t) <= tolerance for t, a in zip(step, angles))


def gesture_forces(force, thumb_force=FIST_THUMB_FORCE):
    forces = [force] * R.N_DOF
    forces[4] = min(force, thumb_force)
    return forces
