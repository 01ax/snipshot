"""Minimal full-screen window on one monitor: how many paints per second does it really get?"""
import os, sys, time
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0"); gi.require_version("Graphene", "1.0")
from gi.repository import Gtk, Gdk, GLib, Graphene

target = sys.argv[1]           # connector name
mode = sys.argv[2]             # fullscreen | maximized
class W(Gtk.Widget):
    __gtype_name__ = "MiniW"
    n = 0
    def do_snapshot(self, snap):
        self.n += 1
        r = Graphene.Rect(); w, h = self.get_width(), self.get_height()
        x = (self.n * 9) % max(1, w - 100)
        c = Gdk.RGBA(red=0.1, green=0.5, blue=1, alpha=1); r.init(x, 100, 100, 100)
        snap.append_color(Gdk.RGBA(red=0, green=0, blue=0, alpha=1), (lambda q: (q.init(0, 0, w, h), q)[1])(Graphene.Rect()))
        snap.append_color(c, r)
class App(Gtk.Application):
    def do_activate(self):
        win = Gtk.Window(application=self, decorated=False)
        wid = W(); wid.set_hexpand(True); wid.set_vexpand(True); win.set_child(wid)
        mons = Gdk.Display.get_default().get_monitors()
        mon = next(mons.get_item(i) for i in range(mons.get_n_items()) if mons.get_item(i).get_connector() == target)
        if mode == "fullscreen": win.fullscreen_on_monitor(mon)
        else: win.maximize()
        win.present()
        t0 = [0, 0]
        def tick():
            wid.queue_draw(); return True
        GLib.timeout_add(8, tick)
        def report():
            n = wid.n
            print(f"{target} {mode}: {n} paints in 3.0 s = {n/3.0:.1f}/s  fullscreen={win.is_fullscreen()} active={win.is_active()}", flush=True)
            self.quit(); return False
        GLib.timeout_add(3500, lambda: (setattr(self, "n0", wid.n), GLib.timeout_add(3000, report), False)[2])
App(application_id="local.snipshot.mini").run([])
