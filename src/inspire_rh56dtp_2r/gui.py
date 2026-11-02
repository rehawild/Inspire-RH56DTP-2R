"""Control panel: a slider per DOF, gestures, live feedback and a tactile heatmap.

    ./rh56 gui            # the real hand
    ./rh56 --sim gui      # built-in simulator

Moving one slider sends only that DOF (the others hold). Esc or Stop cancels
any running gesture and holds the hand where it is. Hand I/O runs on a
background thread so a slow or lost connection never freezes the window.
"""
import threading
import time
import tkinter as tk
from tkinter import ttk

from . import gestures
from . import registers as R
from .hand import decode_errors

LABELS = ("Little", "Ring", "Middle", "Index", "Thumb bend", "Thumb rotate")
DEFAULT_SPEED = 300
DEFAULT_FORCE = 500
SETTLE_S = 0.5            # a gesture step also ends when nothing moved for this long
TACTILE_RANGES = (500, 1000, 2000, 4095)
CELL = 9                  # tactile heatmap cell size, px
PALM_CELL = 14


class HandWorker(threading.Thread):
    """Owns the hand connection: applies queued commands, then publishes feedback."""

    def __init__(self, hand, rate=20.0):
        super().__init__(daemon=True)
        self.hand = hand
        self.period = 1.0 / rate
        self.tactile_enabled = True
        self._lock = threading.Lock()
        self._angles = {}
        self._limits = None
        self._hold = False
        self._clear = False
        self._quit = threading.Event()
        self.snapshot = None          # (time, state, tactile or None, error message or None)

    # -- called from the GUI thread -------------------------------------------

    def set_angles(self, step):
        with self._lock:
            self._angles.update({i: a for i, a in enumerate(step) if a != R.HOLD})

    def set_limits(self, speeds, forces):
        with self._lock:
            self._limits = (list(speeds), list(forces))

    def hold(self):
        with self._lock:
            self._angles.clear()
            self._hold = True

    def clear_errors(self):
        with self._lock:
            self._clear = True

    def stop(self):
        self._quit.set()
        self.join(timeout=2)

    # -- worker thread --------------------------------------------------------

    def run(self):
        while not self._quit.is_set():
            started = time.monotonic()
            try:
                self.step()
            except Exception as e:  # report and retry; the client reconnects by itself
                self.snapshot = (time.monotonic(), None, None, f"{type(e).__name__}: {e}")
                self._quit.wait(0.5)
                continue
            self._quit.wait(max(0.0, self.period - (time.monotonic() - started)))

    def step(self):
        with self._lock:
            angles, self._angles = self._angles, {}
            limits, self._limits = self._limits, None
            hold, self._hold = self._hold, False
            clear, self._clear = self._clear, False
        if clear:
            self.hand.clear_errors()
        if limits:
            self.hand.set_speeds(limits[0])
            self.hand.set_forces(limits[1])
        if hold:
            self.hand.hold()
        elif angles:
            self.hand.set_angles([angles.get(i, R.HOLD) for i in range(R.N_DOF)])
        state = self.hand.read_state()
        tactile = self.hand.read_tactile() if self.tactile_enabled else None
        self.snapshot = (time.monotonic(), state, tactile, None)


def heat_color(value, top):
    """Dark blue -> teal -> yellow -> red."""
    stops = ((0.0, (24, 26, 48)), (0.35, (32, 140, 150)), (0.7, (240, 210, 60)), (1.0, (230, 60, 40)))
    x = min(max(value / top, 0.0), 1.0)
    for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
        if x <= x1:
            f = (x - x0) / (x1 - x0)
            return "#%02x%02x%02x" % tuple(round(a + (b - a) * f) for a, b in zip(c0, c1))
    return "#%02x%02x%02x" % stops[-1][1]


class TactileView(ttk.Frame):
    """Heatmap of all 17 regions, little finger on the left (right hand, palm side)."""

    def __init__(self, parent, on_hover):
        super().__init__(parent)
        self.on_hover = on_hover
        self.range = tk.IntVar(value=1000)
        self.enabled = tk.BooleanVar(value=True)
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Checkbutton(top, text="Tactile", variable=self.enabled).pack(side="left")
        ttk.Label(top, text="  colour range").pack(side="left")
        ttk.Combobox(top, textvariable=self.range, values=TACTILE_RANGES, width=5,
                     state="readonly").pack(side="left", padx=4)
        self.canvas = tk.Canvas(self, width=5 * (8 * CELL + 10) + 10, height=470,
                                background="#111318", highlightthickness=0)
        self.canvas.pack(pady=(4, 0))
        self.cells = {}            # region -> [[item ids]]
        self.where = {}            # item id -> (region, row, col)
        self.region_max = {}       # region -> text item id
        self.colors = {}
        self.frame = None
        self._layout()
        self.canvas.bind("<Motion>", self._hover)

    def _layout(self):
        shapes = {name: (rows, cols) for name, _, rows, cols in R.TACTILE_REGIONS}
        col_w = 8 * CELL + 10
        for f, finger in enumerate(("little", "ring", "middle", "index", "thumb")):
            x0 = 10 + f * col_w
            self.canvas.create_text(x0 + 4 * CELL, 8, text=finger, fill="#aab", font=("TkDefaultFont", 8))
            y = 18
            parts = ("tip", "nail", "middle", "pad") if finger == "thumb" else ("tip", "nail", "pad")
            for part in parts:
                name = f"{finger}_{part}"
                rows, cols = shapes[name]
                self._grid(name, x0 + (8 - cols) * CELL // 2, y, rows, cols, CELL)
                y += rows * CELL + 4
        rows, cols = shapes["palm"]
        x0 = (int(self.canvas["width"]) - cols * PALM_CELL) // 2
        self.canvas.create_text(x0 - 22, 340 + rows * PALM_CELL // 2, text="palm", fill="#aab",
                                font=("TkDefaultFont", 8))
        self._grid("palm", x0, 340, rows, cols, PALM_CELL)

    def _grid(self, name, x0, y0, rows, cols, size):
        ids = []
        for r in range(rows):
            row = []
            for c in range(cols):
                item = self.canvas.create_rectangle(
                    x0 + c * size, y0 + r * size, x0 + (c + 1) * size - 1, y0 + (r + 1) * size - 1,
                    fill="#181a30", outline="")
                self.where[item] = (name, r, c)
                row.append(item)
            ids.append(row)
        self.cells[name] = ids

    def update_frame(self, frame):
        top = self.range.get()
        self.frame = frame
        for name, rows in frame.items():
            ids = self.cells[name]
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    color = heat_color(value, top)
                    item = ids[r][c]
                    if self.colors.get(item) != color:
                        self.canvas.itemconfigure(item, fill=color)
                        self.colors[item] = color

    def _hover(self, event):
        items = self.canvas.find_overlapping(event.x, event.y, event.x, event.y)
        hit = next((self.where[i] for i in items if i in self.where), None)
        if hit and self.frame:
            name, r, c = hit
            self.on_hover(f"{name} row {r + 1} col {c + 1}: {self.frame[name][r][c]}")


class HandPanel:
    PERIOD_MS = 50

    def __init__(self, root, worker, label):
        self.root, self.worker = root, worker
        self.targets = [tk.IntVar(value=1000) for _ in range(R.N_DOF)]
        # Sent on startup: slower and gentler than the hand's power-on 1000 / 2000 g.
        self.speed = tk.IntVar(value=DEFAULT_SPEED)
        self.force = tk.IntVar(value=DEFAULT_FORCE)
        self.thumb_force = tk.IntVar(value=gestures.FIST_THUMB_FORCE)
        self.message = tk.StringVar(value="connecting...")
        self.hover = tk.StringVar(value="")
        self.synced = False          # sliders start where the hand is, on the first feedback
        self.syncing = False
        self.sequence = []           # remaining gesture steps
        self.step = None
        self.total_steps = 0
        self.step_started = 0.0
        self.last_angles = None
        self.last_motion = 0.0
        self.angles = None
        self.sent_limits = None

        root.title(f"Inspire RH56DTP-2R - {label}")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", lambda e: self.stop())
        outer = ttk.Frame(root, padding=10)
        outer.grid(sticky="nsew")
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="nw")
        self.tactile = TactileView(outer, self.hover.set)
        self.tactile.grid(row=0, column=1, sticky="n", padx=(16, 0))
        self._controls(left)
        self._apply_limits()
        root.after(0, self._loop)

    # -- layout ---------------------------------------------------------------

    def _controls(self, frame):
        buttons = ttk.Frame(frame)
        buttons.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))
        for name in gestures.GESTURES:
            ttk.Button(buttons, text=name.capitalize(),
                       command=lambda n=name: self.gesture(n)).pack(side="left", padx=2)
        ttk.Separator(buttons, orient="vertical").pack(side="left", fill="y", padx=6)
        tk.Button(buttons, text="STOP (Esc)", command=self.stop, background="#c62828",
                  foreground="white", activebackground="#e53935").pack(side="left", padx=2)
        ttk.Button(buttons, text="Clear errors", command=self.worker.clear_errors).pack(side="left", padx=2)

        heads = ("", "Target  (0 = closed, 1000 = open)", "Actual", "Force g", "mA", "°C", "Status")
        for col, text in enumerate(heads):
            ttk.Label(frame, text=text, foreground="#666").grid(row=1, column=col, sticky="w", padx=4)
        self.bars, self.values = [], []
        for i, label in enumerate(LABELS):
            row = i + 2
            ttk.Label(frame, text=label, width=12).grid(row=row, column=0, sticky="w")
            tk.Scale(frame, from_=0, to=1000, orient="horizontal", length=340, showvalue=True,
                     variable=self.targets[i], command=lambda _v, i=i: self._on_slider(i)).grid(
                row=row, column=1, padx=4)
            cell = ttk.Frame(frame)
            cell.grid(row=row, column=2, padx=4)
            bar = ttk.Progressbar(cell, maximum=1000, length=120)
            bar.pack(side="left")
            actual = ttk.Label(cell, text="-", width=5, anchor="e")
            actual.pack(side="left")
            labels = [actual]
            for col, width in ((3, 6), (4, 5), (5, 4), (6, 26)):
                lab = tk.Label(frame, text="-", width=width, anchor="e" if col < 6 else "w")
                lab.grid(row=row, column=col, padx=4)
                labels.append(lab)
            self.bars.append(bar)
            self.values.append(labels)

        settings = ttk.Frame(frame)
        settings.grid(row=8, column=0, columnspan=7, sticky="w", pady=(10, 0))
        for text, var, top in (("Speed", self.speed, 1000), ("Force limit g", self.force, 3000),
                               ("Thumb bend limit g", self.thumb_force, 3000)):
            ttk.Label(settings, text=text).pack(side="left", padx=(0, 4))
            tk.Scale(settings, from_=0, to=top, orient="horizontal", length=170, variable=var,
                     resolution=10, command=lambda _v: self._apply_limits()).pack(side="left", padx=(0, 12))

        ttk.Label(frame, textvariable=self.message, wraplength=820).grid(
            row=9, column=0, columnspan=7, sticky="w", pady=(10, 0))
        ttk.Label(frame, textvariable=self.hover, foreground="#666").grid(
            row=10, column=0, columnspan=7, sticky="w")

    # -- user actions ---------------------------------------------------------

    def _apply_limits(self):
        speeds = [self.speed.get()] * R.N_DOF
        forces = gestures.gesture_forces(self.force.get(), self.thumb_force.get())
        if (speeds, forces) != self.sent_limits:
            self.worker.set_limits(speeds, forces)
            self.sent_limits = (speeds, forces)

    def _on_slider(self, i):
        if self.syncing or not self.synced:
            return
        self.sequence, self.step = [], None      # manual input overrides a running gesture
        step = [R.HOLD] * R.N_DOF
        step[i] = self.targets[i].get()
        self.worker.set_angles(step)

    def _send_step(self, step):
        self.step = step
        self.step_started = self.last_motion = time.monotonic()
        self._set_sliders(step)
        self.worker.set_angles(step)

    def gesture(self, name):
        if self.angles is None:
            self.message.set("no feedback from the hand yet")
            return
        steps = gestures.plan(name, self.angles)
        self.total_steps = len(steps)
        self._send_step(steps[0])
        self.sequence = steps[1:]

    def stop(self):
        self.sequence, self.step = [], None
        self.worker.hold()
        self.synced = False                       # re-sync sliders to where it stopped

    def close(self):
        self.worker.stop()
        self.root.destroy()

    def _set_sliders(self, angles):
        self.syncing = True
        try:
            for var, a in zip(self.targets, angles):
                if a != R.HOLD:
                    var.set(a)
        finally:
            self.syncing = False

    # -- feedback loop --------------------------------------------------------

    def _loop(self):
        self.worker.tactile_enabled = self.tactile.enabled.get()
        snap = self.worker.snapshot
        if snap:
            stamp, state, tactile, error = snap
            if error or time.monotonic() - stamp > 1.5:
                self.message.set(f"! no feedback: {error or 'hand not answering'}")
            else:
                self._show(state)
                if tactile:
                    self.tactile.update_frame(tactile)
                self._advance_gesture(state.angle)
        self.root.after(self.PERIOD_MS, self._loop)

    def _show(self, state):
        self.angles = state.angle
        if not self.synced:
            self._set_sliders(state.angle)
            self.synced = True
        problems = []
        for i in range(R.N_DOF):
            self.bars[i]["value"] = state.angle[i]
            actual, force, current, temp, status = self.values[i]
            actual["text"] = str(state.angle[i])
            force["text"] = str(state.force[i])
            current["text"] = str(state.current[i])
            temp["text"] = str(state.temperature[i])
            temp["foreground"] = "#c62828" if state.temperature[i] >= 60 else "black"
            errors = decode_errors(state.error[i])
            if errors:
                status["text"], status["foreground"] = "ERROR: " + ", ".join(errors), "#c62828"
                problems.append(LABELS[i])
            else:
                status["foreground"] = "black"
                status["text"] = R.STATUS_CODES.get(state.status[i], f"code {state.status[i]}")
        if problems:
            self.message.set(f"Errors on {', '.join(problems)}: fix the cause, then Clear errors")
        elif self.step:
            done = self.total_steps - len(self.sequence)
            self.message.set(f"gesture step {done}/{self.total_steps}...")
        else:
            self.message.set("ok")

    def _advance_gesture(self, angles):
        if not self.step:
            return
        now = time.monotonic()
        if self.last_angles is None or max(abs(a - b) for a, b in zip(angles, self.last_angles)) > 2:
            self.last_motion = now
        self.last_angles = angles
        settled = now - self.last_motion > SETTLE_S and now - self.step_started > SETTLE_S
        if gestures.reached(self.step, angles) or settled:
            if self.sequence:
                self._send_step(self.sequence.pop(0))
            else:
                self.step = None


def run(hand, args):
    worker = HandWorker(hand, rate=args.rate)
    worker.start()
    root = tk.Tk()
    label = "simulator" if args.sim else f"{args.ip}:{args.port}"
    HandPanel(root, worker, label)
    try:
        root.mainloop()
    finally:
        worker.stop()
