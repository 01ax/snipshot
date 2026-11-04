"""On a scaled monitor the editor's 100% is real pixels: one picture pixel on one screen pixel, not a magnified copy.

Runs on a private monitor switched to a fractional scale (1.25 here, 1.5 on the real DP-4) and compares what the
compositor actually shows (grabbed from the screen, in device pixels) with the source image."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GSK_RENDERER", "cairo")
import numpy as np
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0")
from gi.repository import Gio, GLib, Gtk
from PIL import Image, ImageDraw
import imaging as im, model as M
import canvas as C
import screencast

fails = 0
def check(n, ok, extra=""):
    global fails; fails += 0 if ok else 1; print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


def set_monitor_scale():
    """Switch the private monitor to 1.5 (the real DP-4) or else 1.25, whichever it supports; returns the scale, or 1.0
    when neither is possible at this monitor size."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    p = Gio.DBusProxy.new_sync(bus, 0, None, "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                               "org.gnome.Mutter.DisplayConfig", None)
    serial, monitors, _logical, _props = p.call_sync("GetCurrentState", None, 0, -1, None).unpack()
    mon = monitors[0]
    mode = next((m for m in mon[1] if m[6].get("is-current")), mon[1][0])
    want = float(os.environ.get("SNIPSHOT_TEST_SCALE", 0))
    order = [want] if want else [1.5, 1.25]
    scale = next((w for w in order if any(abs(w - s) < 1e-3 for s in mode[5])), 1.0)
    if scale == 1.0:
        return 1.0
    cfg = [(0, 0, scale, 0, True, [(mon[0][0], mode[0], {})])]
    p.call_sync("ApplyMonitorsConfig", GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})", (serial, 1, cfg, {})), 0, -1, None)
    return scale


def make_base():
    rng = np.random.default_rng(7)
    img = Image.new("RGB", (800, 400), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i in range(12):
        d.text((10, 10 + i * 16), "The quick brown fox jumps over the lazy dog 0123456789", fill=(0, 0, 0))
    img.paste(Image.fromarray(rng.integers(0, 255, (160, 300, 3), dtype=np.uint8)), (480, 200))   # 1-pixel detail
    return im.from_pil(img), np.asarray(img).astype(int)


def find(screen, patch):
    """Top-left of ``patch`` inside ``screen`` if it is there pixel for pixel, else None."""
    hit = np.argwhere((screen == patch[0, 0]).all(axis=2))
    ph, pw = patch.shape[:2]
    for y, x in hit:
        crop = screen[y:y + ph, x:x + pw]
        if crop.shape == patch.shape and (crop == patch).all():
            return x, y
    return None


class App(Gtk.Application):
    def do_activate(self):
        self.scale = set_monitor_scale()
        self.base, self.src = make_base()
        self.win = Gtk.ApplicationWindow(application=self); self.win.set_default_size(1000, 600)
        self.scene = M.Scene(self.base.copy())
        self.c = C.Canvas(self.scene)
        self.win.set_child(self.c); self.win.present()
        GLib.timeout_add(1500, self.step1)

    def grab(self, then):
        def done(shots, msg):
            self.shot = None if not shots else shots[0].array[..., [2, 1, 0]].astype(int)
            then()
        screencast.capture(done, include_cursor=False)

    def finish(self):
        print("FAILED" if fails else "ALL OK", flush=True)
        self.quit(); return False

    def step1(self):
        c = self.c
        check("the window reports the monitor's scale", abs(c._device_scale() - self.scale) < 1e-4, f"({c._device_scale()} vs {self.scale})")
        if self.scale == 1.0:
            print("SKIP - no fractional scale available in this session"); return self.finish()
        c.zoom_fit()
        check("best fit never magnifies a small picture beyond actual pixels", abs(c.view_zoom() - 1.0) < 1e-6, f"(view zoom {c.view_zoom():.3f})")
        c.zoom_actual()
        check("100% is a logical zoom of 1/scale", abs(c.zoom - 1 / self.scale) < 1e-6, f"({c.zoom:.4f})")
        got = []
        c.on_zoom = got.append
        c.zoom_in()
        check("zoom in goes from 100% to 200%", abs(c.view_zoom() - 2.0) < 1e-6 and abs(got[-1] - 2.0) < 1e-6, f"({c.view_zoom():.3f})")
        c.zoom_out(); c.zoom_out()
        check("zoom out goes from 100% to 75%", abs(c.view_zoom() - 0.75) < 1e-6, f"({c.view_zoom():.3f})")
        c.zoom_actual()
        GLib.timeout_add(900, lambda: self.grab(self.check_100) and False)
        return False

    def check_100(self):
        patch = self.src[200:360, 480:780]
        pos = find(self.shot, patch) if self.shot is not None else None
        check("100%: the 1-pixel noise reaches the screen pixel for pixel", pos is not None)
        if pos:
            x, y = pos
            crop = self.shot[y - 200:y - 200 + 400, x - 480:x - 480 + 800]
            same = (crop == self.src).all(axis=2)[:, :].mean() if crop.shape == self.src.shape else 0
            where = ""
            if crop.shape == self.src.shape and same <= 0.999:
                bad = ~(crop == self.src).all(axis=2)
                rows, cols = bad.sum(axis=1), bad.sum(axis=0)
                where = (f"worst rows {[(int(i), int(rows[i])) for i in np.argsort(-rows)[:3]]}, "
                         f"worst cols {[(int(i), int(cols[i])) for i in np.argsort(-cols)[:3]]}")
            check("100%: the whole picture (text included) is pixel-exact", same > 0.999, f"({same * 100:.2f}% of pixels equal) {where}")
        self.c.set_view_zoom(2.0)
        GLib.timeout_add(900, lambda: self.grab(self.check_200) and False)

    def check_200(self):
        patch = np.repeat(np.repeat(self.src[200:240, 480:540], 2, axis=0), 2, axis=1)
        pos = find(self.shot, patch) if self.shot is not None else None
        check("200%: every picture pixel is exactly 2x2 screen pixels (no blur)", pos is not None)
        self.finish()


App(application_id="local.snipshot.testscale").run([])
sys.exit(1 if fails else 0)
