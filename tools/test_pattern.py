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
# --text STRING: white background with that text in large black letters at (100, 150) - for the OCR tests
text = sys.argv[sys.argv.index("--text") + 1] if "--text" in sys.argv else None
# --window W H: a plain window of that size instead of full screen; --resize-to W H SECONDS: it changes size later
size = resize = None
if "--window" in sys.argv:
    i = sys.argv.index("--window")
    size = (int(sys.argv[i + 1]), int(sys.argv[i + 2]))
if "--resize-to" in sys.argv:
    i = sys.argv.index("--resize-to")
    resize = (int(sys.argv[i + 1]), int(sys.argv[i + 2]), float(sys.argv[i + 3]))


class Area(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self.draw)
        if animate:
            self.add_tick_callback(lambda w, clock: (w.queue_draw(), True)[1])

    def draw(self, _a, cr, w, h):
        if text:
            cr.set_source_rgb(1, 1, 1)
            cr.paint()
            cr.set_source_rgb(0.05, 0.05, 0.05)
            cr.select_font_face("DejaVu Sans")
            cr.set_font_size(44)
            cr.move_to(100, 150)
            cr.show_text(text)
            return
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
    if size:
        win.set_default_size(*size)
        if resize:
            GLib.timeout_add(int(resize[2] * 1000), lambda: (win.set_default_size(resize[0], resize[1]), False)[1])
    else:
        win.fullscreen()
    win.present()


app = Gtk.Application(application_id="local.snipshot.testpattern")
app.connect("activate", activate)
sys.exit(app.run([]))
