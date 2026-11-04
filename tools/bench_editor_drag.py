"""Editor drag benchmark: frames per second while drawing / moving an object over a big image that already has
annotations on it. Run it in the private session so nothing touches the real screens:

    tools/headless_session.sh python3 -I tools/bench_editor_drag.py [WxH] [zoom ...]

BENCH_TOOL=highlight:area (or obfuscate:blur, ellipse, ...) picks the tool; BENCH_EXTENT=2400x1300 makes the dragged object large (default 500x250): lag that grows with the object's size shows there.

Uses fake gestures (like tests/test_canvas.py) and counts frames the way the app really paints them: one drag
update per frame-clock tick, so the rate it reports is the rate you would see while dragging."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GSK_RENDERER", "cairo")
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib
import numpy as np
import imaging as im, model as M
import canvas as C

SIZE = tuple(int(v) for v in (sys.argv[1] if len(sys.argv) > 1 else "3840x2160").split("x"))
ZOOMS = [float(v) for v in sys.argv[2:]] or [0.5, 0.75, 1.0]
SECONDS = 2.0
TOOL = os.environ.get("BENCH_TOOL", "rect")        # rect, ellipse, ... or tool:preset, e.g. highlight:area, obfuscate:blur
EXTENT = tuple(float(v) for v in os.environ.get("BENCH_EXTENT", "500x250").split("x"))     # how far the drag reaches, in picture px


class G:                                   # stand-in for Gtk.GestureDrag
    def __init__(self, sx, sy): self.sx, self.sy = sx, sy
    def get_current_event_state(self): return Gdk.ModifierType(0)
    def get_start_point(self): return True, self.sx, self.sy


def make_scene(n_rects, n_blur):
    w, h = SIZE
    rng = np.random.default_rng(3)
    small = rng.integers(0, 255, (h // 40, w // 40, 4), dtype=np.uint8)
    base = np.repeat(np.repeat(small, 40, axis=0), 40, axis=1)[:h, :w].copy()
    base[..., 3] = 255
    scene = M.Scene(base)
    for i in range(n_rects):
        o = M.new_obj("rect", 100 + i * 25, 100 + i * 15)
        o.x2, o.y2 = o.x1 + 420, o.y1 + 260
        scene.add(o)
    for i in range(n_blur):
        o = M.new_obj("obfuscate", 300 + i * 30, 500)
        o.x2, o.y2 = o.x1 + 500, o.y1 + 200
        o.p["preset"] = "blur"
        scene.add(o)
    return scene


class App(Gtk.Application):
    def do_activate(self):
        self.win = Gtk.ApplicationWindow(application=self)
        self.win.set_default_size(1500, 900)
        self.scene = make_scene(0, 0)
        self.c = C.Canvas(self.scene)
        self.win.set_child(self.c)
        self.draw_ms = []
        inner = self.c._draw
        def timed(area, cr, w, h):
            t = time.perf_counter(); inner(area, cr, w, h); self.draw_ms.append((time.perf_counter() - t) * 1000)
        self.c.area.set_draw_func(timed)
        self.win.present()
        self.jobs = [(z, n, b, tool) for tool in ("create", "move") for (n, b) in ((0, 0), (5, 0), (10, 0), (4, 2))
                     for z in ZOOMS]
        print(f"image {SIZE[0]}x{SIZE[1]}, renderer {os.environ.get('GSK_RENDERER')}", flush=True)
        GLib.timeout_add(800, self.next_job)

    def next_job(self):
        if not self.jobs:
            self.quit()
            return False
        z, n, b, tool = self.jobs.pop(0)
        self.scene.base = make_scene(n, b).base
        self.scene.objects = make_scene(n, b).objects
        self.scene.touch()
        c = self.c
        c.set_zoom(z)
        name, _, preset = TOOL.partition(":")
        if preset:
            c.defaults[name]["preset"] = preset
        c.set_tool(name if tool == "create" else "select")
        self.job = dict(z=z, n=n, b=b, tool=tool, frames=0, t0=None, worst=0.0, last=None)
        if tool == "create":
            ix0, iy0 = 700.0, 900.0
        else:
            o = M.new_obj("rect", 1500, 1000); o.x2, o.y2 = 1900, 1250
            self.scene.add(o); self.scene.touch()
            c.set_tool("select"); c.selection = [o]
            ix0, iy0 = 1500.0, 1000.0
        self.start = (ix0, iy0)
        wx, wy = c.to_widget(ix0, iy0)
        self.g = G(wx, wy)
        # let the layout settle one frame before the drag starts
        GLib.timeout_add(150, self.begin)
        return False

    def begin(self):
        c = self.c
        wx, wy = self.g.sx, self.g.sy
        self.draw_ms.clear()                       # count only the frames of the drag itself
        c._drag_begin(self.g, wx, wy)
        self.tick_id = self.c.area.add_tick_callback(self.tick)
        return False

    def tick(self, widget, clock):
        j = self.job
        now = time.perf_counter()
        if j["t0"] is None:
            j["t0"] = now
        if j["last"] is not None:
            j["worst"] = max(j["worst"], now - j["last"])
        j["last"] = now
        k = now - j["t0"]
        if k > SECONDS:
            self.c._drag_end(self.g, 0, 0)
            fps = j["frames"] / k
            first = self.draw_ms[1] if len(self.draw_ms) > 1 else 0    # [0] is the press itself, [1] the first live frame
            d = sorted(self.draw_ms[2:]) or [0]
            print(f"  {j['tool']:6s} zoom {j['z']:4.2f}  rects {j['n']:2d} blur {j['b']}:  {fps:5.1f} fps, "
                  f"worst frame {j['worst'] * 1000:5.0f} ms; draw func: first {first:5.1f}, median {d[len(d) // 2]:5.1f}, "
                  f"max {d[-1]:5.1f} ms", flush=True)
            GLib.timeout_add(100, self.next_job)
            return False
        j["frames"] += 1
        f = 0.6 + 0.4 * (k % 1.0)
        dx, dy = EXTENT[0] * f, EXTENT[1] * f
        self.c._drag_update(self.g, dx * self.c.zoom, dy * self.c.zoom)
        return True


App(application_id="local.snipshot.benchdrag").run([])
