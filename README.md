# Inspire RH56DTP-2R

Python tools for the **Inspire RH56DTP-2R** right-hand tactile robot hand over
**Ethernet / Modbus TCP**. Includes a desktop control panel, command-line tools,
a simulator, and tests.

## Requirements

- Python 3.8 or newer.
- Tkinter for the GUI (`sudo apt install python3-tk` on Ubuntu).
- An Ethernet connection to the hand for hardware use.

The driver uses Python's standard library. The `./rh56` launcher runs directly
from a checkout; installing the package is optional.

## Try the simulator

From the repository directory:

```bash
./rh56 --sim status
./rh56 --sim gui
```

The GUI provides individual finger sliders, staged gestures, live feedback,
and a tactile sensor view.

## Connect the hand

Power the hand and connect it to the computer's wired Ethernet port. Give that
interface an address on the hand's subnet:

| Setting | Default |
|---|---|
| Hand address | `192.168.11.210` |
| Modbus TCP port | `6000` |
| Example computer address | `192.168.11.100/24` |

The included setup script configures the computer's interface and checks the
connection:

```bash
scripts/setup-network.sh
```

It defaults to interface `eno2`. Set `IFACE` to your wired interface's name if
different, for example `IFACE=enp3s0 scripts/setup-network.sh`. Add
`--persistent` to save the address in the NetworkManager connection profile.

Read the hand's state, then open the control panel:

```bash
./rh56 status
./rh56 gui
```

Opening the GUI applies speed `300`, force limit `500 g`, and thumb-bend force
limit `300 g`. STOP or Escape cancels a gesture and requests a hold at the
measured positions. This depends on the network connection and is not a
hardware emergency stop.

## Useful commands

```bash
./rh56 watch                         # live state
./rh56 tactile                       # tactile sensor summary
./rh56 tactile --region palm --watch # live palm readings
./rh56 hold                          # hold measured positions
./rh56 --ip 192.168.11.210 status     # select a hand address
./rh56 --help                        # all commands and options
```

Axis order: **little, ring, middle, index, thumb bend, thumb rotation**.
Position values use `1000` for open, `0` for closed, and `-1` to leave an axis's
target unchanged.

## Tests

```bash
python3 -m pip install -e ".[test]"
python3 -m pytest
```

Hardware tests are opt-in through `RH56_IP`; motion tests additionally require
`RH56_ALLOW_MOTION=1`. See [the hardware tests](tests/test_hardware.py).

For the Python API, movement commands, protocol details, and hardware-specific
observations, see [the detailed usage and hardware notes](docs/HARDWARE_NOTES.md).
