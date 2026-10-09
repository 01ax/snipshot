"""Record a single window through the desktop's ScreenCast portal.

Mutter's own ScreenCast interface can record a window by id, but a sandbox-free app has no way to ask the user *which*
window. The portal does: it shows the desktop's own picker, then hands back a PipeWire node for the chosen window.
Same interface as castsession.MonitorCast:

    cast = WindowCast(cursor=True, on_closed=...)
    cast.open(cb)       # cb(info, None) when chosen; cb(None, None) if the user cancelled; cb(None, "message") on error
    cast.close()

info = {"node": id, "fd": PipeWire connection to use with that node, "size": (w, h) or None}
"""
import os
import re
import secrets

from gi.repository import Gio, GLib

DESKTOP = "org.freedesktop.portal.Desktop"
DESKTOP_PATH = "/org/freedesktop/portal/desktop"
SC = "org.freedesktop.portal.ScreenCast"
REQUEST = "org.freedesktop.portal.Request"
SESSION = "org.freedesktop.portal.Session"
SOURCE_WINDOW = 2
CURSOR_HIDDEN, CURSOR_EMBEDDED = 1, 2          # (the portal numbers them differently from Mutter)


class WindowCast:
    def __init__(self, cursor=True, on_closed=None, timeout_s=120):
        self.cursor, self.on_closed, self.timeout_s = cursor, on_closed, timeout_s
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.sender = re.sub(r"\W", "_", self.bus.get_unique_name().lstrip(":"))
        self.session = None
        self.fd = None
        self._closed = False
        self._cb = None
        self._subs = []
        self._timer = 0
        self._opened = False

    # -- one portal request: subscribe to its Response before calling, so the reply cannot be missed
    def _request(self, method, build_args, on_response):
        token = "snipshot_" + secrets.token_hex(6)
        path = f"{DESKTOP_PATH}/request/{self.sender}/{token}"

        def got(_c, _s, _p, _i, _sig, params, *_):
            self.bus.signal_unsubscribe(sub)
            if sub in self._subs:
                self._subs.remove(sub)
            code, results = params.unpack()
            on_response(code, results)
        sub = self.bus.signal_subscribe(DESKTOP, REQUEST, "Response", path, None, Gio.DBusSignalFlags.NONE, got)
        self._subs.append(sub)
        try:
            self.bus.call_sync(DESKTOP, DESKTOP_PATH, SC, method, build_args(token), None, Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error as e:
            self.bus.signal_unsubscribe(sub)
            self._subs.remove(sub)
            self._fail(f"The desktop's screen recording service is unavailable: {e.message}")

    def open(self, callback):
        self._cb = callback
        self._timer = GLib.timeout_add_seconds(self.timeout_s, self._on_timeout)
        self._request("CreateSession", lambda t: GLib.Variant("(a{sv})", ({
            "handle_token": GLib.Variant("s", t), "session_handle_token": GLib.Variant("s", "snipshot_s" + secrets.token_hex(4)),
        },)), self._created)

    def _created(self, code, results):
        if code != 0 or "session_handle" not in results:
            return self._fail("The desktop refused to start a screen recording session")
        self.session = results["session_handle"]
        self._subs.append(self.bus.signal_subscribe(DESKTOP, SESSION, "Closed", self.session, None,
                                                    Gio.DBusSignalFlags.NONE, self._session_closed))
        self._request("SelectSources", lambda t: GLib.Variant("(oa{sv})", (self.session, {
            "handle_token": GLib.Variant("s", t), "types": GLib.Variant("u", SOURCE_WINDOW),
            "multiple": GLib.Variant("b", False),
            "cursor_mode": GLib.Variant("u", CURSOR_EMBEDDED if self.cursor else CURSOR_HIDDEN),
            "persist_mode": GLib.Variant("u", 0),
        })), self._selected)

    def _selected(self, code, results):
        if code != 0:
            return self._fail("The desktop refused the window recording request")
        self._request("Start", lambda t: GLib.Variant("(osa{sv})", (self.session, "", {"handle_token": GLib.Variant("s", t)})),
                      self._started)

    def _started(self, code, results):
        if code == 1:                                   # the person closed the picker
            return self._cancel()
        streams = results.get("streams") if code == 0 else None
        if not streams:
            return self._fail("No window was chosen")
        node, props = streams[0]
        size = props.get("size")
        try:
            _res, fds = self.bus.call_with_unix_fd_list_sync(
                DESKTOP, DESKTOP_PATH, SC, "OpenPipeWireRemote",
                GLib.Variant("(oa{sv})", (self.session, {})), GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, 5000, None, None)
            self.fd = fds.get(0)
        except GLib.Error as e:
            return self._fail(f"Could not connect to the window's video stream: {e.message}")
        self._opened = True
        self._clear_timer()
        cb, self._cb = self._cb, None
        if cb:
            cb({"node": node, "fd": self.fd, "size": tuple(size) if size else None}, None)

    def _session_closed(self, *_):
        if not self._closed and self._opened and self.on_closed:
            self.on_closed()

    def _on_timeout(self):
        self._timer = 0
        self._fail("No window was chosen in time")
        return False

    def _clear_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _cancel(self):
        cb, self._cb = self._cb, None
        self.close()
        if cb:
            cb(None, None)

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
        for sub in self._subs:
            self.bus.signal_unsubscribe(sub)
        self._subs = []
        if self.session:
            try:
                self.bus.call_sync(DESKTOP, self.session, SESSION, "Close", None, None, Gio.DBusCallFlags.NONE, 2000, None)
            except GLib.Error:
                pass
            self.session = None
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
