"""The editor draws a drag from a cached picture instead of re-rendering everything on each mouse move.

Checks that what is shown mid-drag is the same picture a full render would give (so nothing jumps when you let go),
at zooms that exercise every drawing path, and that a drag really does skip the full render."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GSK_RENDERER", "cairo")
import numpy as np
import cairo
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib
import imaging as im, model as M, render as R
import canvas as C

fails = 0
def check(n, ok, extra=""):
    global fails; fails += 0 if ok else 1; print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


class G:                                   # stand-in for Gtk.GestureDrag
    def __init__(self, sx, sy): self.sx, self.sy = sx, sy
    def get_current_event_state(self): return Gdk.ModifierType(0)
    def get_start_point(self): return True, self.sx, self.sy


def shot(c):
    """What the canvas paints, as an array (the whole drawing area, scrolled out of the picture)."""
    w, h = (int(v) for v in c._area_size())
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    c._draw(None, cairo.Context(surf), w, h)
    return im.from_surface(surf).astype(int)


def make_scene():
    rng = np.random.default_rng(5)
    small = rng.integers(0, 255, (90, 160, 4), dtype=np.uint8)
    base = np.repeat(np.repeat(small, 8, axis=0), 8, axis=1)[:700, :1250].copy()    # 1250 x 700, odd-ish, blocky
    base[..., 3] = 255
    s = M.Scene(base)
    for i, kind in enumerate(("rect", "ellipse", "arrow")):
        o = M.new_obj(kind, 60 + i * 40, 60 + i * 30); o.x2, o.y2 = o.x1 + 300, o.y1 + 180
        s.add(o)
    return s


class App(Gtk.Application):
    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self); win.set_default_size(900, 700)
        self.scene = make_scene()
        self.c = C.Canvas(self.scene)
        win.set_child(self.c); win.present()
        GLib.timeout_add(500, self.run_tests)

    def run_tests(self):
        global fails
        try:
            self.tests()
        except Exception:
            import traceback; traceback.print_exc(); fails += 1
        print("FAILED" if fails else "ALL OK", flush=True)
        self.quit()
        return False

    def tests(self):
        c, sc = self.c, self.scene
        full_renders = []
        orig = R.render_scene
        R.render_scene = lambda *a, **k: (full_renders.append(1), orig(*a, **k))[1]
        try:
            for zoom in (0.3, 0.45, 0.75, 1.0, 2.5):
                c.set_zoom(zoom)
                c.set_tool("rect")
                shot(c)                                            # an idle frame first, as in real use
                p0 = c.to_widget(500, 300)
                g = G(*p0)
                before = len(full_renders)
                c._drag_begin(g, *p0)
                for k in range(1, 6):                              # five mouse moves
                    c._drag_update(g, k * 35 * zoom, k * 20 * zoom)
                    live = shot(c)
                check(f"zoom {zoom}: a drag does not run the full render", len(full_renders) == before)
                c._drag_end(g, 175 * zoom, 100 * zoom)
                c.selection = []                                   # (the new object's handles are not part of the picture)
                done = shot(c)                                     # after release: the normal full render
                diff = np.abs(live - done)
                check(f"zoom {zoom}: mid-drag picture equals the finished one", diff.max() <= 2,
                      f"(max difference {diff.max()}, {int((diff.max(axis=2) > 0).sum())} px differ)")
                c.undo()

            # filter tools work on the pixels below them (and the dim / grey ones are cached once per drag): same picture too
            for tool, props in (("highlight", dict(preset="area")), ("highlight", dict(preset="gray")),
                                ("highlight", dict(preset="magnify")), ("obfuscate", dict(preset="blur"))):
                c.defaults[tool].update(props)
                for zoom in (0.45, 1.0):
                    c.set_zoom(zoom); c.set_tool(tool); shot(c)
                    p0 = c.to_widget(500, 300); g = G(*p0)
                    c._drag_begin(g, *p0)
                    for k in range(1, 5):
                        c._drag_update(g, k * 40 * zoom, k * 25 * zoom)
                        live = shot(c)
                    c._drag_end(g, 160 * zoom, 100 * zoom)
                    c.selection = []
                    done = shot(c)
                    diff = np.abs(live - done)
                    check(f"{tool} {props['preset']} at zoom {zoom}: mid-drag picture equals the finished one", diff.max() == 0,
                          f"(max difference {diff.max()})")
                    c.undo()

            # moving an object that has others above it, one of them a blur: the stack above must be redrawn too
            o_blur = M.new_obj("obfuscate", 100, 100); o_blur.x2, o_blur.y2 = 700, 400; o_blur.p["preset"] = "blur"
            sc.add(o_blur)
            top = M.new_obj("rect", 650, 350); top.x2, top.y2 = 900, 500
            sc.add(top)
            sc.touch()
            low = sc.objects[1]
            for zoom in (0.4, 1.0):
                c.set_zoom(zoom); c.set_tool("select"); shot(c)
                c.selection = [low]
                p0 = c.to_widget(low.x1, low.y1 + 90)
                g = G(*p0)
                c._drag_begin(g, *p0)
                for k in range(1, 5):
                    c._drag_update(g, 30 * k * zoom, 10 * k * zoom)
                    live = shot(c)
                c._drag_end(g, 120 * zoom, 40 * zoom)
                done = shot(c)
                diff = np.abs(live - done)
                check(f"zoom {zoom}: moving a low object under a blur matches the full render", diff.max() <= 2,
                      f"(max difference {diff.max()})")
                c.undo()
                sc.touch()

            # undo while dragging replaces the objects: the editor must not crash or draw stale objects
            c.set_zoom(0.5); c.set_tool("rect"); shot(c)
            p0 = c.to_widget(200, 450); g = G(*p0)
            c._drag_begin(g, *p0); c._drag_update(g, 40, 30); shot(c)
            n = len(sc.objects)
            c.undo()
            try:
                c._drag_update(g, 60, 40); shot(c); ok = True
            except Exception as e:
                ok = False; print(repr(e))
            check("undo in the middle of a drag does not break drawing", ok)
            c._drag_end(g, 60, 40)
        finally:
            R.render_scene = orig


App(application_id="local.snipshot.testlive").run([])
sys.exit(1 if fails else 0)
