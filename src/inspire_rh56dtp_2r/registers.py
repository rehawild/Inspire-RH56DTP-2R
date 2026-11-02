"""Register map of the Inspire RH56DFTP/RH56DTP tactile hand.

Source: Inspire Robots "The Dexterous Hand RH56DFTP User Manual",
PRJ-02-TS-U-010 V1.0.0 (Dec 2024), section 2.6.

Addresses are *byte* addresses into the hand's register memory. Over Modbus
the hand uses the byte address as the register address, and reading N
registers returns 2N consecutive bytes. Multi-byte values are little-endian
in memory, so a register's value is ``mem[a] | mem[a + 1] << 8`` and is sent
big-endian on the wire like any Modbus register. Byte-wide arrays (ERROR,
STATUS, TEMP) therefore come back two entries per register, low byte first.
"""

DOF_NAMES = ("little", "ring", "middle", "index", "thumb_bend", "thumb_rotate")
N_DOF = len(DOF_NAMES)

DEFAULT_IP = "192.168.11.210"
DEFAULT_PORT = 6000

# Configuration (1 byte each unless noted)
HAND_ID = 1000
REDU_RATIO = 1002            # RS485 baud: 0=115200 1=57600 2=19200 3=921600
CLEAR_ERROR = 1004           # write 1
SAVE = 1005                  # write 1 to store parameters in flash
RESET_PARA = 1006            # write 1 to restore factory defaults
FORCE_CALIBRATE = 1009       # write 1, palm open and touching nothing
DEFAULT_SPEED_SET = 1032     # 6 x int16, 0..1000, power-on speed
DEFAULT_FORCE_SET = 1044     # 6 x int16, 0..3000 g, power-on force limit
IP_PART1 = 1700              # 4 x u8 (1700..1703), effective after power cycle

# Control and feedback (6 x int16 unless noted)
POS_SET = 1474               # 0..2000 actuator stroke, -1 = no action
ANGLE_SET = 1486             # 0..1000 (1000 = open), -1 = no action
FORCE_SET = 1498             # 0..3000 g force limit
SPEED_SET = 1522             # 0..1000 (1000 = full stroke in ~0.6 s unloaded)
POS_ACT = 1534               # 0..2000
ANGLE_ACT = 1546             # 0..1000
FORCE_ACT = 1582             # -4000..4000 g
CURRENT = 1594               # 0..2000 mA
ERROR = 1606                 # 6 x u8 bit flags, see ERROR_BITS
STATUS = 1612                # 6 x u8, see STATUS_CODES
TEMP = 1618                  # 6 x u8, deg C

# One read from POS_SET through TEMP covers every control/feedback block.
STATE_START = POS_SET
STATE_END = TEMP + N_DOF     # exclusive byte address
STATE_REGS = (STATE_END - STATE_START) // 2

ANGLE_RANGE = (0, 1000)
SPEED_RANGE = (0, 1000)
FORCE_RANGE = (0, 3000)
HOLD = -1                    # "leave this DOF where it is" in *_SET blocks

ERROR_BITS = {
    0: "locked rotor",
    1: "over temperature",
    2: "overcurrent",
    3: "motor fault",
    4: "communication error",
}

# Not in the DFTP manual; taken from the RH56 series manual. 255 is what an
# idle hand reports after power-up before it has been given a target. The RH56
# manual calls 7 a fault stop, but the DTP reports it on a DOF that is holding
# still with no error bits set, so it is shown as a bare code. ERROR is the
# authoritative fault signal.
STATUS_CODES = {
    0: "releasing",
    1: "grasping",
    2: "reached position",
    3: "reached force limit",
    5: "stopped: current protection",
    6: "stopped: locked rotor",
    255: "idle",
}

# Tactile regions: (name, byte address, rows, cols). One int16 (0..4095) per
# cell. Finger regions are row-major. The palm is column-major starting from
# the bottom row (manual 2.6.20), which read_tactile() undoes.
TACTILE_REGIONS = (
    ("little_tip", 3000, 3, 3),
    ("little_nail", 3018, 12, 8),
    ("little_pad", 3210, 10, 8),
    ("ring_tip", 3370, 3, 3),
    ("ring_nail", 3388, 12, 8),
    ("ring_pad", 3580, 10, 8),
    ("middle_tip", 3740, 3, 3),
    ("middle_nail", 3758, 12, 8),
    ("middle_pad", 3950, 10, 8),
    ("index_tip", 4110, 3, 3),
    ("index_nail", 4128, 12, 8),
    ("index_pad", 4320, 10, 8),
    ("thumb_tip", 4480, 3, 3),
    ("thumb_nail", 4498, 12, 8),
    ("thumb_middle", 4690, 3, 3),
    ("thumb_pad", 4708, 12, 8),
    ("palm", 4900, 8, 14),
)
TACTILE_START = 3000
TACTILE_END = 4900 + 8 * 14 * 2
TACTILE_MAX = 4095
