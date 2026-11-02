# Detailed usage and hardware notes

Run the commands below from the repository root.

Tools for the **Inspire RH56DTP-2R** (right hand, tactile) over Ethernet / Modbus TCP:
a small Python driver, a command-line tool, a simulator and tests.
Pure standard library, Python 3.8+.

| | |
|---|---|
| Hand address | `192.168.11.210:6000` (factory default, Modbus TCP) |
| This PC | needs an address on `192.168.11.0/24`, e.g. `192.168.11.100` |
| DOF order | little, ring, middle, index, thumb_bend, thumb_rotate |
| Angles | 0..1000, **1000 = open**, `-1` = leave that DOF where it is |
| Speed | 0..1000 (1000 ≈ full stroke in 0.6 s unloaded) |
| Force limit | 0..3000 g at the fingertip |
| Tactile | 17 regions, 0..4095 per cell, full frame in ~20 ms |

Register map and protocol notes are in [`src/inspire_rh56dtp_2r/registers.py`](../src/inspire_rh56dtp_2r/registers.py),
taken from the *RH56DFTP User Manual* PRJ-02-TS-U-010 V1.0.0 (same protocol as the DTP).

## 1. Network

The hand has no DHCP server. Connect it to the PC's wired port (`eno2` here) and add a
static address on its subnet:

```bash
scripts/setup-network.sh               # temporary, until the link resets
scripts/setup-network.sh --persistent  # saved in the NetworkManager profile
```

The script ends by checking that `192.168.11.210:6000` answers.

## 2. Use it

### Control panel

```bash
./rh56 gui            # the real hand
./rh56 --sim gui      # simulator, no hardware
```

- A slider per DOF; moving one sends only that DOF, the others hold.
- **Open / Fist / Point / Thumbs up** run step by step: each stage starts when the previous
  one has reached its target or stopped moving, and the thumb is lifted and swung out first
  if it is across the palm.
- **STOP** (or Esc) cancels a running gesture and holds the hand where it is.
- Live angle, force, current, temperature and status per DOF; errors show in red.
- Tactile heatmap of all 17 regions (little finger on the left, palm below); hover a cell
  for its value. Untick *Tactile* to stop polling it.
- Speed, force limit and a separate thumb-bend limit. Opening the panel sets them to
  300 / 500 g / 300 g, gentler than the hand's power-on 1000 / 2000 g.

Hand I/O runs on a background thread at 20 Hz (`--rate`), so a lost connection shows a
message instead of freezing the window; it reconnects by itself.

### Command line

```bash
./rh56 status                 # one read: angles, targets, force, current, temperature, errors
./rh56 watch                  # live view
./rh56 tactile                # per-region max/sum
./rh56 tactile --region palm --watch
```

Moving (defaults: speed 300, force limit 500 g; refuses to start while the hand reports an error):

```bash
./rh56 open                   # if the thumb is across the palm, it is lifted and swung out first
./rh56 close                  # four fingers only; thumb is left alone to avoid collisions
./rh56 fist                   # fingers, then thumb across the palm, then bent over (see below)
./rh56 move 1000 1000 1000 500 -1 -1    # index halfway, the rest unchanged
./rh56 demo                   # each DOF halfway and back, one at a time
./rh56 hold                   # stay at the measured position
./rh56 clear-errors
```

`fist` bends the thumb to 600 with a 300 g force limit on that joint (`--thumb-force`). With the
thumb rotated in it first touches the index finger at ~800, so this is a firm fist without the
thumb grinding into the index finger. The index force reading goes wrong while the thumb
presses on it.

Ctrl+C while a move is in progress commands the hand to hold where it is. That is a software
hold over the network, **not an emergency stop**; cut the 24 V supply for that.

Add `--sim` to any command to run it against the built-in simulator instead of the hand,
or run a standalone simulator with `python3 -m inspire_rh56dtp_2r.sim --port 6000`.

From Python:

```python
from inspire_rh56dtp_2r import RH56Hand

with RH56Hand("192.168.11.210") as hand:
    print(hand.read_state())
    hand.set_speeds([300] * 6)
    hand.set_forces([500] * 6)
    hand.set_angles({"index": 500})          # missing DOFs hold
    print(hand.wait_until_settled().angle)
    frame = hand.read_tactile()              # {"index_tip": [[...], ...], ..., "palm": [...]}
```

`pip install -e .` also installs an `rh56` command.

## 3. Tests

```bash
python3 -m pytest                                     # protocol + simulator, no hardware
RH56_IP=192.168.11.210 python3 -m pytest tests/test_hardware.py -v     # read-only checks on the hand
RH56_IP=192.168.11.210 RH56_ALLOW_MOTION=1 python3 -m pytest tests/test_hardware.py -v
```

The motion test only moves the index finger to 500 and back, slowly with a 500 g limit.

## Notes

- Every Modbus write gets an answer that must be read, or the hand stops responding; the
  client always reads it. It also tolerates firmware that echoes wrong transaction IDs.
- Register addresses are byte addresses; byte-wide blocks (errors, status, temperature)
  come back two per register, low byte first.
- At rest some force readings are offset by a few hundred grams. If that matters, run the
  force calibration (register 1009) with the palm open and touching nothing; it isn't exposed
  in the CLI on purpose.
- The hand also has an FTDI USB–RS485 link (`/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_BG027RQ5-if00-port0`,
  115200 8N1, ID 1). This repo only uses Ethernet. Serial access needs the `dialout` group.
- Changing the hand's IP (registers 1700–1703, effective after a power cycle) is deliberately
  not wrapped here.
