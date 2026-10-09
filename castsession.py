"""A long-lived Mutter ScreenCast stream for one monitor, used as the video source of a recording.

(screencast.py takes single frames for screenshots; this keeps the session open until the recording is finished.)
Mutter hands out the monitor's real pixels as a PipeWire node; the node id goes to ``recorder`` as the video source.
Mutter only sends a frame when something on screen changes, so the recorder asks pipewiresrc to repeat the last frame
(``keepalive-time``) to keep the video's timing even while the screen is still.
"""
from gi.repository import Gio, GLib

SC = "org.gnome.Mutter.ScreenCast"
SC_PATH = "/org/gnome/Mutter/ScreenCast"
CURSOR_HIDDEN, CURSOR_EMBEDDED = 0, 1


class MonitorCast:
    """``open(cb)`` calls ``cb(info, None)`` once the stream exists, or ``cb(None, message)``. ``close()`` ends it.

    info = {"node": PipeWire node id, "fd": None (Mutter's nodes live on the normal PipeWire socket), "size": (w, h) or
    None}. ``on_closed()`` is called if the compositor ends the session by itself (the screen was locked, ...)."""

    def __init__(self, connector, cursor=True, size=None, timeout_ms=5000, on_closed=None):
        self.connector, self.cursor, self.size, self.timeout_ms = connector, cursor, size, timeout_ms
        self.on_closed = on_closed
        self._closed_sub = None
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.session = None
        self.stream = None
        self.node = None
        self._sub = None
        self._timer = 0
        self._cb = None
        self._closed = False

    def _call(self, path, iface, method, sig, args):
        return self.bus.call_sync(SC, path, iface, method, GLib.Variant(sig, args) if sig else None, None,
                                  Gio.DBusCallFlags.NONE, 5000, None).unpack()

    def open(self, callback):
        self._cb = callback
        try:
            (self.session,) = self._call(SC_PATH, SC, "CreateSession", "(a{sv})", ({},))
            mode = CURSOR_EMBEDDED if self.cursor else CURSOR_HIDDEN
            (self.stream,) = self._call(self.session, SC + ".Session", "RecordMonitor", "(sa{sv})",
                                        (self.connector, {"cursor-mode": GLib.Variant("u", mode)}))
            self._sub = self.bus.signal_subscribe(SC, SC + ".Stream", "PipeWireStreamAdded", self.stream, None,
                                                  Gio.DBusSignalFlags.NONE, self._on_added)
            self._closed_sub = self.bus.signal_subscribe(SC, SC + ".Session", "Closed", self.session, None,
                                                         Gio.DBusSignalFlags.NONE, self._on_session_closed)
            self._call(self.session, SC + ".Session", "Start", None, None)
        except GLib.Error as e:
            self._fail(f"Screen capture is unavailable: {e.message}")
            return
        self._timer = GLib.timeout_add(self.timeout_ms, self._on_timeout)

    def _on_added(self, _c, _s, _path, _i, _sig, params, *_):
        if self.node is not None or self._closed:
            return
        self.node = params.unpack()[0]
        self._clear_timer()
        cb, self._cb = self._cb, None
        if cb:
            cb({"node": self.node, "fd": None, "size": self.size}, None)

    def _on_session_closed(self, *_):
        if not self._closed and self.node is not None and self.on_closed:
            self.on_closed()

    def _on_timeout(self):
        self._timer = 0
        self._fail("Screen capture did not start (is the screen locked?)")
        return False

    def _clear_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _fail(self, msg):
        cb, self._cb = self._cb, None
        self.close()
        if cb:
            cb(None, msg)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._clear_timer()
        for attr in ("_sub", "_closed_sub"):
            if getattr(self, attr) is not None:
                self.bus.signal_unsubscribe(getattr(self, attr))
                setattr(self, attr, None)
        if self.session:
            try:
                self._call(self.session, SC + ".Session", "Stop", None, None)
            except GLib.Error:
                pass
            self.session = None
