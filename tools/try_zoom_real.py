import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, GLib
import imaging as im, model as M, canvas as C
class App(Gtk.Application):
    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self); win.set_default_size(900, 650)
        self.c = C.Canvas(M.Scene(im.blank(2000, 1500, (230, 235, 240, 255)))); win.set_child(self.c); win.present()
        self.n = 0; GLib.timeout_add(1200, self.step)
    def under(self, view):
        c = self.c; h, v = c.get_hadjustment(), c.get_vadjustment(); ox, oy = c._origin()
        return ((view[0] + h.get_value() - ox) / c.zoom, (view[1] + v.get_value() - oy) / c.zoom)
    def step(self):
        c = self.c; h, v = c.get_hadjustment(), c.get_vadjustment(); self.n += 1
        if self.n == 1:
            real = c.pointer_view()
            self.view = real if real is not None else (c.get_width() / 2, c.get_height() / 2)
            print("pointer source:", "REAL device position" if real is not None else "window centre (pointer is elsewhere)", self.view, flush=True)
            c.set_zoom(1.0); h.set_value(200); v.set_value(150)
            self.target = self.under(self.view); self.worst = 0.0; rnd = random.Random(11)
            if real is None: c._pointer_override = self.view
            for i in range(50):
                c.handle_ctrl_scroll(-1 if rnd.random() < 0.55 else 1)
                p = self.under(self.view)
                edge = h.get_value() <= 0.01 or v.get_value() <= 0.01 or h.get_value() >= c._area_size()[0] - c._page()[0] - 0.01 or v.get_value() >= c._area_size()[1] - c._page()[1] - 0.01
                if i < 14 or (not edge and max(abs(p[0] - self.target[0]), abs(p[1] - self.target[1])) * c.zoom > 1):
                    print(f"  step {i:2d} zoom {c.zoom:6.3f} scroll=({h.get_value():8.2f},{v.get_value():8.2f}) range=({c._area_size()[0]-c._page()[0]:.0f},{c._area_size()[1]-c._page()[1]:.0f}) page={c._page()} err={max(abs(p[0]-self.target[0]),abs(p[1]-self.target[1]))*c.zoom:7.2f} edge={edge}", flush=True)
                if edge: self.target = p
                else: self.worst = max(self.worst, max(abs(p[0] - self.target[0]), abs(p[1] - self.target[1])) * c.zoom)
            self.snap = (h.get_value(), v.get_value(), c.zoom)
            print(f"50 random notches, immediate check: worst drift {self.worst:.3f} px (zoom now {c.zoom:.2f})", flush=True)
        elif self.n == 2:
            nh, nv = h.get_value() - self.snap[0], v.get_value() - self.snap[1]
            print(f"after real layout: scroll moved by ({nh:.2f}, {nv:.2f}) px -> {'NO late jolt' if abs(nh) < 0.6 and abs(nv) < 0.6 else 'LATE JOLT'}", flush=True)
            aw, ah = c._area_size()
            print(f"computed area {aw}x{ah} vs real {c.area.get_width()}x{c.area.get_height()}", flush=True)
            self.quit(); return False
        return True
App(application_id="local.snipshot.realzoom").run([])
