"""Registers a tray icon on the real session bus, then checks it through the same D-Bus calls a tray host makes.
Calls are asynchronous because the service lives in this same process / main loop."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gi.repository import Gio, GLib
import tray as T

EXPECTED = 6
fired = []
tray = T.TrayIcon("Snipshot test", "image-x-generic", [
    {"label": "Capture region", "callback": lambda: fired.append("region")},
    {"label": "Capture full screen", "callback": lambda: fired.append("full")},
    None,
    {"label": "Quit", "callback": lambda: fired.append("quit")},
], on_activate=lambda: fired.append("activate"))
loop = GLib.MainLoop()
res = []
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)


def check(name, ok, extra=""):
    res.append(bool(ok))
    print(("PASS" if ok else "FAIL"), "-", name, extra, flush=True)


def acall(dest, path, iface, method, sig, args, then):
    def done(conn, r):
        try:
            then(conn.call_finish(r).unpack())
        except GLib.Error as e:
            check(f"{method} call", False, str(e))
            loop.quit()
    bus.call(dest, path, iface, method, GLib.Variant(sig, args) if sig else None, None,
             Gio.DBusCallFlags.NONE, 4000, None, done)


def start_checks():
    check("registered with the StatusNotifierWatcher", tray.registered)
    acall(T.WATCHER[0], T.WATCHER[1], "org.freedesktop.DBus.Properties", "Get", "(ss)",
          (T.WATCHER[2], "RegisteredStatusNotifierItems"), after_watcher)
    return False


def after_watcher(r):
    items = r[0]
    check("watcher lists our item", any(tray.bus_name in s for s in items))
    acall(tray.bus_name, T.MENU_PATH, "com.canonical.dbusmenu", "GetLayout", "(iias)", (0, -1, []), after_layout)


def after_layout(r):
    _rev, layout = r
    kids = layout[2]
    labels = [k[1].get("label") for k in kids]
    check("menu has 4 entries", len(kids) == 4)
    check("labels right, separator typed", labels == ["Capture region", "Capture full screen", None, "Quit"]
          and kids[2][1].get("type") == "separator", str(labels))
    # click item 2 ("Capture full screen"), then the separator (3, must be ignored), then primary-click the icon
    acall(tray.bus_name, T.MENU_PATH, "com.canonical.dbusmenu", "Event", "(isvu)",
          (2, "clicked", GLib.Variant("i", 0), 0),
          lambda _: acall(tray.bus_name, T.MENU_PATH, "com.canonical.dbusmenu", "Event", "(isvu)",
                          (3, "clicked", GLib.Variant("i", 0), 0),
                          lambda _: acall(tray.bus_name, T.ITEM_PATH, "org.kde.StatusNotifierItem", "Activate",
                                          "(ii)", (0, 0), finish)))


def finish(_):
    GLib.timeout_add(300, final)


def final():
    check("clicking a menu item runs its callback", fired.count("full") == 1 and "quit" not in fired, str(fired))
    check("primary click calls on_activate", "activate" in fired)
    tray.stop()
    loop.quit()
    return False


tray.start()
GLib.timeout_add(1200, start_checks)
GLib.timeout_add_seconds(20, loop.quit)
loop.run()
ok = len(res) == EXPECTED and all(res)
print("\nALL PASSED" if ok else f"\nFAILED ({sum(res)}/{EXPECTED} checks passed)")
sys.exit(0 if ok else 1)
