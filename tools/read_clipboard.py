"""Print the text on the clipboard (private headless session only; a tiny window is needed to receive the clipboard)."""
import os
import sys

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("read_clipboard only runs inside tools/headless_session.sh")
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

app = Gtk.Application(application_id="local.snipshot.readclip")


def activate(a):
    win = Gtk.ApplicationWindow(application=a)
    win.set_default_size(200, 100)
    win.present()

    def read():
        win.get_clipboard().read_text_async(None, lambda c, r: (print(repr(c.read_text_finish(r))), a.quit()))
        return False
    GLib.timeout_add(1500, read)
    GLib.timeout_add_seconds(8, a.quit)


app.connect("activate", activate)
app.run([])
