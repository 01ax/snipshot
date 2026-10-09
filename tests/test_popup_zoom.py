import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, GLib
import imaging as im, model as M, canvas as C
fails = 0
def check(n, ok, extra=""):
    global fails; fails += 0 if ok else 1; print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)
class App(Gtk.Application):
    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self); win.set_default_size(700, 500)
        sc = M.Scene(im.blank(1600, 1200, (230, 235, 240, 255)))
        self.c = C.Canvas(sc); win.set_child(self.c); win.present()
        self.sc = sc; self.n = 0
        GLib.timeout_add(700, self.step)
    def step(self):
        c, sc = self.c, self.sc
        self.n += 1
        h, v = c.get_hadjustment(), c.get_vadjustment()
        if self.n == 1:
            r = sc.add(M.Obj("rect", 100, 100, 300, 250, fill_color=(1, 1, 1, 1))); c.select([r])
            try:
                c.show_context_menu(150, 150); ok = c._ctx_popover is not None
            except Exception as e:
                ok = False; print("error:", e)
            check("right-click popover menu opens without error", ok)
            c._ctx_popover.popdown()
            r2 = sc.add(M.Obj("ellipse", 500, 500, 700, 650, fill_color=(1, 1, 1, 1))); c.select([])
            wx, wy = c.to_widget(600, 575); c._right_click(None, 1, wx, wy)
            check("right-clicking an unselected object selects it", c.selection == [r2])
            c._ctx_popover.popdown()
            # three wheel notches in a row, with the mouse not moving, around image point (300, 220)
            c.set_zoom(1.0)
        elif self.n == 2:
            self.target = (300.0, 220.0)
            wx, wy = c.to_widget(*self.target)
            self.view = (wx - h.get_value(), wy - v.get_value())
            c._pointer_override = self.view
            for _ in range(3):
                c.handle_ctrl_scroll(-1)
            self.z = c.zoom
        elif self.n == 4:
            wx, wy = c.to_widget(*self.target)
            vx, vy = wx - h.get_value(), wy - v.get_value()
            check("three fast notches zoom 25% each", abs(self.z - 1.25 ** 3) < 1e-6, f"{self.z:.3f}")
            check("...and the point under the pointer stayed put on screen", abs(vx - self.view[0]) < 4 and abs(vy - self.view[1]) < 4,
                  f"was ({self.view[0]:.0f},{self.view[1]:.0f}) now ({vx:.0f},{vy:.0f})")
            # zoom back out the same way: the point must still be under the pointer
            for _ in range(3):
                c.handle_ctrl_scroll(1)
        elif self.n == 6:
            wx, wy = c.to_widget(*self.target)
            vx, vy = wx - h.get_value(), wy - v.get_value()
            check("zooming back out also keeps it under the pointer", abs(vx - self.view[0]) < 4 and abs(vy - self.view[1]) < 4,
                  f"now ({vx:.0f},{vy:.0f}), zoom {c.zoom:.3f}")
            print("\nFAILED" if fails else "\nALL PASSED", fails or "", flush=True); self.quit(); os._exit(1 if fails else 0)
        return True
App(application_id="local.snipshot.t3").run([])
