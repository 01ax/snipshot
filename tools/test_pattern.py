"""A full-screen window with known content, shown in the private headless session so recordings can be checked.

Left third red, middle third green, right third blue; with --static nothing moves, otherwise a white square runs
along the bottom so every frame differs. Only ever started by the headless tests."""
import os
import sys

os.environ.setdefault("GSK_RENDERER", "cairo")
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

animate = "--static" not in sys.argv


class Area(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self.draw)
        if animate:
            self.add_tick_callback(lambda w, clock: (w.queue_draw(), True)[1])

    def draw(self, _a, cr, w, h):
        for i, rgb in enumerate(((1, 0, 0), (0, 1, 0), (0, 0, 1))):
            cr.set_source_rgb(*rgb)
            cr.rectangle(i * w / 3, 0, w / 3 + 1, h)
            cr.fill()
        if animate:
            t = GLib.get_monotonic_time() / 1e6
            cr.set_source_rgb(1, 1, 1)
            cr.rectangle((t * 300) % (w - 60), h - 80, 60, 60)
            cr.fill()


def activate(app):
    win = Gtk.ApplicationWindow(application=app)
    win.set_decorated(False)
    win.set_child(Area())
    win.fullscreen()
    win.present()


app = Gtk.Application(application_id="local.snipshot.testpattern")
app.connect("activate", activate)
sys.exit(app.run([]))
