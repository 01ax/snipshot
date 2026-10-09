"""Ctrl+wheel zoom must keep the picture point under the pointer fixed: after EVERY notch, immediately and after
GTK has laid everything out."""
import os, random, sys
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
        win = Gtk.ApplicationWindow(application=self); win.set_default_size(800, 600)
        self.sc = M.Scene(im.blank(2000, 1500, (230, 235, 240, 255)))
        self.c = C.Canvas(self.sc); win.set_child(self.c); win.present()
        self.stage = 0
        GLib.timeout_add(800, self.run_stage)

    def pt_under(self, view):
        """Picture point currently under a view position, from the live scroll values."""
        c = self.c; h, v = c.get_hadjustment(), c.get_vadjustment()
        ox, oy = c._origin()
        return ((view[0] + h.get_value() - ox) / c.zoom, (view[1] + v.get_value() - oy) / c.zoom)

    def run_stage(self):
        c = self.c; h, v = c.get_hadjustment(), c.get_vadjustment()
        st = self.stage; self.stage += 1
        if st == 0:
            check("viewport does not scroll to the focused widget", c.get_child().get_scroll_to_focus() is False)
            c.set_zoom(1.0)
        elif st == 1:
            rnd = random.Random(7)
            view = (320.0, 240.0); c._pointer_override = view
            c.set_zoom(1.0); h.set_value(150); v.set_value(120)
            target = self.pt_under(view)
            worst = 0.0; n_bad = 0
            for i in range(60):
                c.handle_ctrl_scroll(-1 if rnd.random() < 0.55 else 1)
                p = self.pt_under(view)                  # immediately, before GTK lays out anything
                err = max(abs(p[0] - target[0]), abs(p[1] - target[1])) * c.zoom
                at_edge = h.get_value() <= 0.01 or v.get_value() <= 0.01 or \
                    h.get_value() >= c._area_size()[0] - c._page()[0] - 0.01 or v.get_value() >= c._area_size()[1] - c._page()[1] - 0.01
                if not at_edge:
                    worst = max(worst, err)
                    n_bad += err > 0.6
                if at_edge:                              # clamped by the scroll range: re-anchor like a real user would
                    target = self.pt_under(view)
            check("60 random notches: the point under the pointer never moves (checked immediately)", n_bad == 0, f"worst error {worst:.3f} px, {n_bad} bad")
            self.final = (c.zoom, h.get_value(), v.get_value(), self.pt_under(view), view)
        elif st == 3:
            z, hv, vv, p, view = self.final
            check("after GTK lays out: scroll position unchanged (no late jolt)", abs(h.get_value() - hv) < 0.6 and abs(v.get_value() - vv) < 0.6,
                  f"h {hv:.1f}->{h.get_value():.1f} v {vv:.1f}->{v.get_value():.1f}")
            aw, ah = c._area_size()
            check("computed area size equals the real allocation", abs(aw - c.area.get_width()) <= 1 and abs(ah - c.area.get_height()) <= 1,
                  f"{aw}x{ah} vs {c.area.get_width()}x{c.area.get_height()}")
            # in and out again with a stationary pointer returns to exactly where it started
            c.set_zoom(1.0); h.set_value(300); v.set_value(200); c._zoom_anchor = None
            view = (400.0, 300.0); c._pointer_override = view
            start = (h.get_value(), v.get_value())
            for _ in range(5): c.handle_ctrl_scroll(-1)
            for _ in range(5): c.handle_ctrl_scroll(1)
            check("5 notches in then 5 out returns to the same zoom and position",
                  abs(c.zoom - 1.0) < 1e-9 and abs(h.get_value() - start[0]) < 1.0 and abs(v.get_value() - start[1]) < 1.0,
                  f"zoom {c.zoom:.4f} scroll ({h.get_value():.1f},{v.get_value():.1f}) vs {start}")
            # mouse jitter of a few pixels while scrolling must not shift the anchor
            c.set_zoom(1.0); h.set_value(300); v.set_value(200); c._zoom_anchor = None
            jit = random.Random(3); drift = 0.0; v0 = target = None
            for i in range(30):
                view = (400.0 + jit.uniform(-2.5, 2.5), 300.0 + jit.uniform(-2.5, 2.5)); c._pointer_override = view
                if i == 0:
                    v0 = view; target = self.pt_under(v0)   # the gesture is anchored where the first notch happens
                c.handle_ctrl_scroll(-1 if i % 3 else 1)
                p = self.pt_under(v0)                        # that point must stay under that spot, whatever the jitter
                drift = max(drift, max(abs(p[0] - target[0]), abs(p[1] - target[1])) * c.zoom)
            check("pointer jitter of +/-2.5 px does not make the picture drift", drift < 1.5, f"max {drift:.2f} px")
            # moving the pointer to a new spot re-anchors there
            c.set_zoom(1.0); h.set_value(300); v.set_value(200); c._zoom_anchor = None
            c._pointer_override = (200.0, 150.0); c.handle_ctrl_scroll(-1)
            c._pointer_override = (600.0, 400.0)
            before = self.pt_under((600.0, 400.0)); c.handle_ctrl_scroll(-1); after = self.pt_under((600.0, 400.0))
            check("after moving the pointer, the new spot is the anchor", max(abs(before[0] - after[0]), abs(before[1] - after[1])) * c.zoom < 0.6,
                  f"{before} -> {after}")
            # the scenario behind the 'jolt': zoom out until the scroll range runs out (the point can no longer be
            # held under the pointer), then zoom back in. It must continue from what is actually under the pointer.
            c.set_zoom(2.0); h.set_value(0); v.set_value(0); c._zoom_anchor = None
            c._pointer_override = (100.0, 80.0)
            for _ in range(4): c.handle_ctrl_scroll(1)             # zoom out: the scroll position hits its limit
            before = self.pt_under((100.0, 80.0)); c.handle_ctrl_scroll(-1); after = self.pt_under((100.0, 80.0))
            check("zooming back in after hitting the scroll limit does not jump to the old anchor",
                  max(abs(before[0] - after[0]), abs(before[1] - after[1])) * c.zoom < 0.6, f"{before} -> {after}")
            for _ in range(3): c.handle_ctrl_scroll(-1)
            p1 = self.pt_under((100.0, 80.0)); c.handle_ctrl_scroll(-1); p2 = self.pt_under((100.0, 80.0))
            check("...and stays put on the following notches", max(abs(p1[0] - p2[0]), abs(p1[1] - p2[1])) * c.zoom < 0.6)
            # starting from 'best fit' (picture smaller than the view), zooming in must stay stable and not error
            c._pointer_override = (350.0, 250.0); c.zoom_fit()
        elif st == 4:
            ok = True
            try:
                for _ in range(12):
                    c.handle_ctrl_scroll(-1)
            except Exception as e:
                ok = False; print("error:", e)
            check("zooming in from best fit works", ok and c.zoom > 1.0, f"zoom {c.zoom:.2f}")
            # focus changes must not scroll
            c.set_zoom(3.0); h.set_value(500); v.set_value(400); self.keep = (h.get_value(), v.get_value())
            c.area.grab_focus()
            o = self.sc.add(M.Obj("text", 600, 500, 700, 540)); c.begin_text_edit(o, is_new=True)
        elif st == 6:
            check("focusing the canvas and the text editor does not move the picture",
                  abs(h.get_value() - self.keep[0]) < 0.6 and abs(v.get_value() - self.keep[1]) < 0.6,
                  f"{self.keep} -> ({h.get_value():.1f},{v.get_value():.1f})")
            c._finish_text_edit()
            print("\nFAILED" if fails else "\nALL PASSED", fails or "", flush=True); self.quit(); os._exit(1 if fails else 0)
        return True
App(application_id="local.snipshot.t4").run([])
