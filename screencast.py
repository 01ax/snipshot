"""Native-resolution, per-monitor screen capture through Mutter's ScreenCast interface.

Why not the screenshot portal? On GNOME it (a) composites every monitor at the highest monitor scale, so a 1.0x
monitor is blown up 1.5x and looks soft next to a 1.5x one, (b) plays the shutter sound and flashes the screen,
(c) leaves the mouse cursor out, and (d) takes ~1.7 s. ScreenCast hands out each monitor's real pixels in ~0.1 s,
with no effects. The mouse cursor is found by capturing each monitor twice at the same moment, once without and
once with the cursor drawn in, and taking the difference.

PipeWire frames are read with GStreamer's ``pipewiresrc``.
"""
import time
from dataclasses import dataclass, field

import gi
import numpy as np

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import Gio, GLib, Gst, GstApp  # noqa: E402,F401

SC = "org.gnome.Mutter.ScreenCast"
SC_PATH = "/org/gnome/Mutter/ScreenCast"
CURSOR_HIDDEN, CURSOR_EMBEDDED = 0, 1


@dataclass
class MonitorInfo:
    connector: str
    x: int                      # logical position
    y: int
    w: int                      # logical size
    h: int
    scale: float
    pw: int                     # native pixels
    ph: int
    primary: bool = False


@dataclass
class MonitorShot:
    info: MonitorInfo
    array: np.ndarray                                   # native pixels, BGRA premultiplied, opaque
    cursor: tuple = None                                # (sprite BGRA array, x, y) in native pixels, or None


# --------------------------------------------------------------------------- monitors

def list_monitors():
    """Monitors with their logical geometry, scale and real (native) pixel size, from Mutter's display config."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    r = bus.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                      "org.gnome.Mutter.DisplayConfig", "GetCurrentState", None, None, Gio.DBusCallFlags.NONE,
                      5000, None).unpack()
    _serial, monitors, logical, _props = r
    modes = {}
    for (conn, _v, _p, _s), mode_list, _mp in monitors:
        cur = [m for m in mode_list if m[6].get("is-current")]
        if cur:
            modes[conn] = (cur[0][1], cur[0][2])
    out = []
    for x, y, scale, transform, primary, mons, _lp in logical:
        conn = mons[0][0]
        pw, ph = modes.get(conn, (0, 0))
        if transform in (1, 3, 5, 7):                    # rotated 90/270: the panel's width and height swap
            pw, ph = ph, pw
        out.append(MonitorInfo(conn, x, y, int(round(pw / scale)), int(round(ph / scale)), float(scale), pw, ph,
                               bool(primary)))
    return sorted(out, key=lambda m: (m.x, m.y))


# --------------------------------------------------------------------------- cursor

CURSOR_DIFF_THRESHOLD = 20
CURSOR_MAX_SIZE = 220


def extract_cursor(clean, with_cursor):
    """Compare a frame without the cursor to one with it. Returns (sprite, x, y) in pixels, or None.

    Only a small blob counts: if the two frames differ over a large area, something on screen changed between
    them (a video, a clock) and the difference is not the cursor."""
    if clean.shape != with_cursor.shape:
        return None
    diff = np.abs(clean[..., :3].astype(np.int16) - with_cursor[..., :3].astype(np.int16)).max(axis=2)
    mask = diff > CURSOR_DIFF_THRESHOLD
    if not mask.any():
        return None
    rows, cols = np.where(mask.any(axis=1))[0], np.where(mask.any(axis=0))[0]
    y0, y1, x0, x1 = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
    if y1 - y0 > CURSOR_MAX_SIZE or x1 - x0 > CURSOR_MAX_SIZE:
        return None
    sub_mask = mask[y0:y1, x0:x1]
    # grow the mask by one pixel so the anti-aliased rim of the arrow is kept
    grown = sub_mask.copy()
    grown[1:] |= sub_mask[:-1]
    grown[:-1] |= sub_mask[1:]
    grown[:, 1:] |= sub_mask[:, :-1]
    grown[:, :-1] |= sub_mask[:, 1:]
    sprite = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
    sprite[grown] = with_cursor[y0:y1, x0:x1][grown]
    sprite[..., 3] = np.where(grown, 255, 0)
    sprite[~grown] = 0
    return sprite, x0, y0


# --------------------------------------------------------------------------- capture

class _Capture:
    """One capture run. Everything happens on the GLib main loop; GStreamer's callbacks hop back via idle_add."""

    def __init__(self, monitors, include_cursor, callback, timeout_ms):
        if not Gst.is_initialized():               # only when a capture really happens, not at import time
            Gst.init(None)
        self.monitors = monitors
        self.include_cursor = include_cursor
        self.callback = callback
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.session = None
        self.streams = {}              # stream path -> (monitor index, cursor_mode)
        self.nodes = {}                # stream path -> pipewire node id
        self.frames = {}               # stream path -> array
        self.pipes = []
        self.subs = []
        self.done = False
        self.t0 = time.time()
        self.timer = GLib.timeout_add(timeout_ms, self._timeout)

    def _call(self, path, iface, method, sig, args):
        return self.bus.call_sync(SC, path, iface, method, GLib.Variant(sig, args) if sig else None, None,
                                  Gio.DBusCallFlags.NONE, 5000, None).unpack()

    def start(self):
        try:
            (self.session,) = self._call(SC_PATH, SC, "CreateSession", "(a{sv})", ({},))
            modes = [CURSOR_HIDDEN] + ([CURSOR_EMBEDDED] if self.include_cursor else [])
            for i, m in enumerate(self.monitors):
                for mode in modes:
                    (stream,) = self._call(self.session, SC + ".Session", "RecordMonitor", "(sa{sv})",
                                           (m.connector, {"cursor-mode": GLib.Variant("u", mode)}))
                    self.streams[stream] = (i, mode)
                    self.subs.append(self.bus.signal_subscribe(
                        SC, SC + ".Stream", "PipeWireStreamAdded", stream, None, Gio.DBusSignalFlags.NONE,
                        self._on_stream_added))
            self._call(self.session, SC + ".Session", "Start", None, None)
        except GLib.Error as e:
            self._finish(None, f"ScreenCast unavailable: {e.message}")

    def _on_stream_added(self, _c, _s, path, _i, _sig, params, *_):
        if self.done or path in self.nodes:
            return
        self.nodes[path] = params.unpack()[0]
        sink_pipe = Gst.parse_launch(
            f"pipewiresrc path={self.nodes[path]} always-copy=true ! videoconvert ! video/x-raw,format=BGRx ! "
            "appsink name=s emit-signals=true max-buffers=1 drop=true sync=false")
        sink = sink_pipe.get_by_name("s")
        sink.connect("new-sample", self._on_sample, path)
        self.pipes.append(sink_pipe)
        sink_pipe.set_state(Gst.State.PLAYING)

    def _on_sample(self, sink, path):
        """Runs on a GStreamer thread: copy the frame out and hand over to the main loop."""
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        st = sample.get_caps().get_structure(0)
        w, h = st.get_value("width"), st.get_value("height")
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            try:
                stride = info.size // h
                frame = np.frombuffer(info.data, dtype=np.uint8, count=h * stride).reshape(h, stride)[:, : w * 4]
                frame = frame.reshape(h, w, 4).copy()
            finally:
                buf.unmap(info)
            frame[..., 3] = 255                           # BGRx: the fourth byte is padding
            GLib.idle_add(self._got_frame, path, frame)
        return Gst.FlowReturn.OK

    def _got_frame(self, path, frame):
        if self.done or path in self.frames:
            return False
        self.frames[path] = frame
        if len(self.frames) == len(self.streams):
            self._finish(self._assemble(), "")
        return False

    def _assemble(self):
        shots = []
        for i, m in enumerate(self.monitors):
            clean = next((self.frames[p] for p, (idx, mode) in self.streams.items() if idx == i and mode == CURSOR_HIDDEN), None)
            with_c = next((self.frames[p] for p, (idx, mode) in self.streams.items() if idx == i and mode == CURSOR_EMBEDDED), None)
            if clean is None:
                return None
            cur = extract_cursor(clean, with_c) if with_c is not None else None
            shots.append(MonitorShot(m, clean, cur))
        return shots

    def _timeout(self):
        self.timer = 0
        self._finish(None, "ScreenCast timed out")
        return False

    def _finish(self, shots, msg):
        if self.done:
            return
        self.done = True
        if self.timer:
            GLib.source_remove(self.timer)
        for p in self.pipes:
            p.set_state(Gst.State.NULL)
        for s in self.subs:
            self.bus.signal_unsubscribe(s)
        if self.session:
            try:
                self._call(self.session, SC + ".Session", "Stop", None, None)
            except GLib.Error:
                pass
        self.callback(shots, msg)


def capture(callback, monitors=None, include_cursor=True, timeout_ms=4000):
    """Capture every monitor (or the given ones). ``callback(shots or None, message)`` runs on the main loop."""
    try:
        monitors = monitors or list_monitors()
    except GLib.Error as e:
        callback(None, f"Could not read the monitor layout: {e.message}")
        return
    _Capture(monitors, include_cursor, callback, timeout_ms).start()


# --------------------------------------------------------------------------- combining monitors

def combine(shots):
    """All monitors as one image, each at its own native pixels (nothing is rescaled), side by side in screen order.
    Heights may differ, so shorter monitors are top-aligned. Returns (array, [(shot, x, y)])."""
    shots = sorted(shots, key=lambda s: (s.info.x, s.info.y))
    width = sum(s.array.shape[1] for s in shots)
    height = max(s.array.shape[0] for s in shots)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    out[..., 3] = 255
    placed, x = [], 0
    for s in shots:
        h, w = s.array.shape[:2]
        out[:h, x:x + w] = s.array
        placed.append((s, x, 0))
        x += w
    return out, placed
