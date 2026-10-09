"""Synthetic mouse and keyboard input for the PRIVATE headless session, through Mutter's RemoteDesktop interface.

Only meaningful inside tools/headless_session.sh (it refuses to run anywhere else, so it can never move the pointer
of the real desktop).

    inp = RemoteInput()
    inp.move(300, 200); inp.click(); inp.drag((100, 100), (400, 300)); inp.key("Return"); inp.key("r")
"""
import os
import time

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib

RD = "org.gnome.Mutter.RemoteDesktop"
RD_PATH = "/org/gnome/Mutter/RemoteDesktop"
SC = "org.gnome.Mutter.ScreenCast"
SC_PATH = "/org/gnome/Mutter/ScreenCast"
BTN_LEFT, BTN_RIGHT = 0x110, 0x111


class RemoteInput:
    def __init__(self, connector="Meta-0"):
        if os.environ.get("SNIPSHOT_HEADLESS") != "1":
            raise RuntimeError("RemoteInput only runs inside tools/headless_session.sh")
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        (self.rd,) = self._call(RD, RD_PATH, RD, "CreateSession", None)
        sid = self._get(self.rd, RD + ".Session", "SessionId")
        (self.sc,) = self._call(SC, SC_PATH, SC, "CreateSession", "(a{sv})", ({"remote-desktop-session-id": GLib.Variant("s", sid)},))
        (self.stream,) = self._call(SC, self.sc, SC + ".Session", "RecordMonitor", "(sa{sv})", (connector, {}))
        self._call(RD, self.rd, RD + ".Session", "Start", None)
        time.sleep(0.4)
        # The first press of a key the virtual keyboard has not used yet can be swallowed while Mutter maps the symbol,
        # so touch the keys the tests use now, while nothing is listening.
        for name in ("a", "m", "r", "s", "v", "z", "Return", "Escape"):
            self.key(name)

    def _call(self, dest, path, iface, method, sig, args=None):
        v = GLib.Variant(sig, args) if sig else None
        return self.bus.call_sync(dest, path, iface, method, v, None, Gio.DBusCallFlags.NONE, 5000, None).unpack()

    def _get(self, path, iface, prop):
        return self.bus.call_sync(RD, path, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (iface, prop)),
                                  None, Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]

    def _rd(self, method, sig, args):
        self._call(RD, self.rd, RD + ".Session", method, sig, args)

    def close(self):
        try:
            self._call(RD, self.rd, RD + ".Session", "Stop", None)
        except GLib.Error:
            pass

    # -- pointer
    def move(self, x, y, settle=0.08):
        self._rd("NotifyPointerMotionAbsolute", "(sdd)", (self.stream, float(x), float(y)))
        time.sleep(settle)

    def button(self, down, button=BTN_LEFT):
        self._rd("NotifyPointerButton", "(ib)", (button, bool(down)))
        time.sleep(0.06)

    def click(self, x=None, y=None, button=BTN_LEFT):
        if x is not None:
            self.move(x, y)
        self.button(True, button)
        self.button(False, button)
        time.sleep(0.15)

    def drag(self, a, b, steps=8):
        self.move(*a)
        self.button(True)
        for i in range(1, steps + 1):
            self.move(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps, settle=0.04)
        self.button(False)
        time.sleep(0.2)

    # -- keyboard (names as in Gdk.KEY_*, e.g. "Return", "Escape", "r")
    def key(self, name):
        sym = getattr(Gdk, "KEY_" + name)
        self._rd("NotifyKeyboardKeysym", "(ub)", (sym, True))
        time.sleep(0.04)
        self._rd("NotifyKeyboardKeysym", "(ub)", (sym, False))
        time.sleep(0.2)
