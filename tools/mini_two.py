import os, sys
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0"); gi.require_version("Graphene", "1.0")
from gi.repository import Gtk, Gdk, GLib, Graphene
class W(Gtk.Widget):
    __gtype_name__ = "MiniW2"
    n = 0
    def do_snapshot(self, snap):
        self.n += 1
        w, h = self.get_width(), self.get_height()
        r = Graphene.Rect(); r.init(0, 0, w, h)
        snap.append_color(Gdk.RGBA(red=0, green=0, blue=0, alpha=1), r)
        r2 = Graphene.Rect(); r2.init((self.n * 9) % max(1, w - 100), 100, 100, 100)
        snap.append_color(Gdk.RGBA(red=0.1, green=0.5, blue=1, alpha=1), r2)
class App(Gtk.Application):
    def do_activate(self):
        mons = Gdk.Display.get_default().get_monitors()
        self.items = []
        for i in range(mons.get_n_items()):
            win = Gtk.Window(application=self, decorated=False)
            wid = W(); wid.set_hexpand(True); wid.set_vexpand(True); win.set_child(wid)
            win.fullscreen_on_monitor(mons.get_item(i)); win.present()
            self.items.append((mons.get_item(i).get_connector(), win, wid))
        GLib.timeout_add(8, lambda: ([w.queue_draw() for _, _, w in self.items], True)[1])
        def snap0(): self.s0 = [w.n for _, _, w in self.items]; return False
        def report():
            for (c, win, w), a in zip(self.items, self.s0):
                print(f"{c}: {(w.n - a)/3.0:.1f} paints/s  active={win.is_active()}", flush=True)
            self.quit(); return False
        GLib.timeout_add(2500, snap0); GLib.timeout_add(5500, report)
App(application_id="local.snipshot.mini2").run([])
