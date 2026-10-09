"""Screen capture front end for Snipshot on Wayland.

* ``grab`` takes every monitor at its native resolution through Mutter's ScreenCast (see screencast.py): no
  shutter sound, no flash, no 1.5x blow-up of the 1.0x monitor, and the mouse cursor comes back as its own sprite.
  If ScreenCast is not available it falls back to the screenshot portal.
* ``RegionSelector`` shows each monitor's frozen frame 1:1 on a full-screen window per monitor and lets you drag a
  rectangle, like Greenshot's region capture (M toggles the mouse cursor, Z the zoomer, Esc cancels).
  The selection stays on the monitor where you started dragging, so the result is always real pixels.
  A toolbar at the top switches the same overlay between taking a screenshot and recording the screen (S / R keys);
  in record mode it also holds the system-sound and microphone switches.
"""
import os
import random
import time

import gi
import numpy as np

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, Gio, GLib, Graphene, Gsk, Gtk  # noqa: E402

import icons as IC  # noqa: E402
import imaging as im  # noqa: E402
import screencast as SCN  # noqa: E402

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"


# --------------------------------------------------------------------------- grabbing

def grab(callback, include_cursor=True):
    """callback(list[MonitorShot] or None, message). Native pixels via ScreenCast, else the portal."""
    def done(shots, msg):
        if shots:
            callback(shots, "")
            return
        portal_screenshot(lambda arr, m: callback(_shots_from_composite(arr) if arr is not None else None,
                                                  m or msg))
    SCN.capture(done, include_cursor=include_cursor)


def _shots_from_composite(arr):
    """Slice a portal screenshot (all monitors at one scale) into per-monitor shots."""
    layout = monitor_layout()
    x0, y0, sx, sy = image_scale(arr.shape[1], arr.shape[0], layout)
    shots = []
    for (mx, my, mw, mh), mon in zip(layout, Gdk.Display.get_default().get_monitors()):
        ix, iy, iw, ih = logical_to_image((mx, my, mw, mh), (x0, y0, sx, sy), arr.shape[1], arr.shape[0])
        info = SCN.MonitorInfo(mon.get_connector() or f"monitor{len(shots)}", mx, my, mw, mh, iw / max(mw, 1), iw, ih)
        shots.append(SCN.MonitorShot(info, arr[iy:iy + ih, ix:ix + iw].copy()))
    return shots


def portal_screenshot(callback, interactive=False, timeout_s=30):
    """Ask xdg-desktop-portal for a screenshot. ``callback(array_or_None, message)`` runs on the main loop.

    Used for window capture (the desktop's own picker) and as a fallback. It makes the desktop play the shutter
    sound and flash, which is why region/full-screen capture use ScreenCast instead."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    token = f"snipshot{random.randrange(10**9)}"
    sender = bus.get_unique_name()[1:].replace(".", "_")
    request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
    state = {"done": False, "sub": 0, "timer": 0}

    def finish(arr, msg):
        if state["done"]:
            return
        state["done"] = True
        if state["sub"]:
            bus.signal_unsubscribe(state["sub"])
        if state["timer"]:
            GLib.source_remove(state["timer"])
        callback(arr, msg)

    def on_response(_c, _s, _p, _i, _sig, params, *_):
        code, results = params.unpack()
        if code != 0:
            finish(None, "Screenshot cancelled" if code == 1 else "The screenshot was refused by the desktop")
            return
        path = Gio.File.new_for_uri(results.get("uri", "")).get_path()
        try:
            arr = im.load_file(path)
        except Exception as e:           # noqa: BLE001 - report any decode problem to the user
            finish(None, f"Could not read the screenshot: {e}")
            return
        finally:
            _remove_portal_file(path)
        finish(arr, "")

    state["sub"] = bus.signal_subscribe(PORTAL, "org.freedesktop.portal.Request", "Response", request_path, None,
                                        Gio.DBusSignalFlags.NONE, on_response)

    def reply(conn, res):
        try:
            conn.call_finish(res)
        except GLib.Error as e:
            finish(None, f"Screenshot portal error: {e.message}")

    options = {"handle_token": GLib.Variant("s", token), "interactive": GLib.Variant("b", interactive)}
    bus.call(PORTAL, PORTAL_PATH, "org.freedesktop.portal.Screenshot", "Screenshot",
             GLib.Variant("(sa{sv})", (_parent_handle(), options)), None, Gio.DBusCallFlags.NONE, -1, None, reply)
    state["timer"] = GLib.timeout_add_seconds(timeout_s, lambda: (finish(None, "The screenshot timed out"), False)[1])


def _parent_handle():
    """xdg-desktop-portal-gnome (46+) rejects an empty parent window; "wayland:" means 'no particular parent'."""
    return "wayland:" if os.environ.get("WAYLAND_DISPLAY") else ""


def _remove_portal_file(path):
    """Delete the portal's temporary file, but only if it is clearly the one just created for us."""
    try:
        if path and os.path.isfile(path) and abs(time.time() - os.path.getmtime(path)) < 120 \
                and os.path.basename(path).lower().startswith(("screenshot", "snipshot")):
            os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------- monitor geometry (portal fallback)

def monitor_layout():
    """[(x, y, w, h)] of every GTK monitor in logical pixels, in GTK's order."""
    out = []
    for m in Gdk.Display.get_default().get_monitors():
        g = m.get_geometry()
        out.append((g.x, g.y, g.width, g.height))
    return out


def image_scale(image_w, image_h, layout):
    """(x0, y0, sx, sy): logical origin of the desktop and image pixels per logical pixel."""
    x0 = min(m[0] for m in layout)
    y0 = min(m[1] for m in layout)
    lw = max(m[0] + m[2] for m in layout) - x0
    lh = max(m[1] + m[3] for m in layout) - y0
    return x0, y0, image_w / lw, image_h / lh


def logical_to_image(rect, geom, image_w, image_h):
    """(x, y, w, h) in logical desktop px -> integer pixels in the screenshot, clamped to it."""
    x0, y0, sx, sy = geom
    x1, y1 = (rect[0] - x0) * sx, (rect[1] - y0) * sy
    x2, y2 = (rect[0] + rect[2] - x0) * sx, (rect[1] + rect[3] - y0) * sy
    ix1, iy1 = max(0, int(round(x1))), max(0, int(round(y1)))
    ix2, iy2 = min(image_w, int(round(x2))), min(image_h, int(round(y2)))
    return ix1, iy1, max(0, ix2 - ix1), max(0, iy2 - iy1)


def logical_to_native(rect, info, arr_w, arr_h):
    """A logical-pixel rectangle on one monitor (relative to that monitor) -> that monitor's real pixels."""
    fx, fy = arr_w / max(info.w, 1), arr_h / max(info.h, 1)
    x1, y1 = max(0, int(round(rect[0] * fx))), max(0, int(round(rect[1] * fy)))
    x2, y2 = min(arr_w, int(round((rect[0] + rect[2]) * fx))), min(arr_h, int(round((rect[1] + rect[3]) * fy)))
    return x1, y1, max(0, x2 - x1), max(0, y2 - y1)


def cursor_in_region(shot, region):
    """The shot's cursor sprite placed relative to ``region`` (x, y, w, h native), or None if it is outside."""
    if not shot.cursor:
        return None
    sprite, cx, cy = shot.cursor
    x, y, w, h = region
    sh, sw = sprite.shape[:2]
    if cx + sw <= x or cx >= x + w or cy + sh <= y or cy >= y + h:
        return None
    return sprite, cx - x, cy - y


# --------------------------------------------------------------------------- region selection

def _rect(x, y, w, h):
    r = Graphene.Rect()
    r.init(x, y, max(0.0, w), max(0.0, h))
    return r


def _point(x, y):
    p = Graphene.Point()
    p.init(x, y)
    return p


def _texture(arr):
    """Upload a BGRA premultiplied array to the GPU once; every frame after that is just a draw call."""
    h, w = arr.shape[:2]
    return Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, GLib.Bytes.new(arr.tobytes()), w * 4)


DIM = Gdk.RGBA(red=0, green=0, blue=0, alpha=0.38)
LINE = Gdk.RGBA(red=0.11, green=0.52, blue=1.0, alpha=1.0)
LINE_REC = Gdk.RGBA(red=0.94, green=0.27, blue=0.27, alpha=1.0)        # the outline turns red in record mode
CROSS = Gdk.RGBA(red=1, green=1, blue=1, alpha=0.6)
PILL = Gdk.RGBA(red=0.04, green=0.04, blue=0.07, alpha=0.88)
WHITE = Gdk.RGBA(red=1, green=1, blue=1, alpha=1)
LOUPE_BG = Gdk.RGBA(red=0, green=0, blue=0, alpha=1)
LOUPE_PX = 7                    # logical pixels per native pixel inside the zoomer
LOUPE_SIZE = 140


class _Shared:
    """Selection shared by every monitor's overlay window (global logical coordinates)."""

    def __init__(self):
        self.start = None
        self.cur = None
        self.anchor = None           # index of the window where the drag began; the selection never leaves it
        self.hover = None            # (gx, gy) of the pointer
        self.hover_win = None
        self.armed = False           # record mode: a rectangle is chosen and waits for the Start button / Enter
        self.windows = []

    def rect(self):
        if not self.start or not self.cur:
            return None
        x1, y1 = self.start
        x2, y2 = self.cur
        return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)

    def redraw(self, only=None):
        """Repaint every overlay, or just the windows at the given indices. Repainting a monitor that did not
        change costs a blocking buffer swap on the single UI thread, which starved the other monitor."""
        for i, w in enumerate(self.windows):
            if only is None or i in only:
                w.area.queue_draw()


class _Canvas(Gtk.Widget):
    """Draws with GTK's scene graph (GPU) instead of cairo (CPU): rescaling a 4K picture in software took about half
    a second per frame, which made the selection lag far behind the mouse pointer."""
    __gtype_name__ = "SnipshotRegionCanvas"

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_cursor_from_name("crosshair")

    def do_snapshot(self, snapshot):
        self.owner.paint(self, snapshot)


def _icon_label(icon, text):
    box = Gtk.Box(spacing=6)
    img = IC.ui_image(icon, 18)
    box.append(img)
    box.append(Gtk.Label(label=text))
    return box, img


class _Toolbar(Gtk.Box):
    """Top bar of the overlay: Screenshot | Record, then (recording) system sound / microphone, mouse pointer, and
    the Window... and This screen shortcuts. It only shows and edits the selector's state."""

    def __init__(self, selector):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.selector = selector
        self._syncing = False
        self.add_css_class("snipshot-toolbar")
        self.b_shot, _ = self._toggle("camera", "Screenshot", "Take a screenshot  (S)")
        self.b_rec, _ = self._toggle("record", "Record", "Record the screen  (R)")
        self.b_rec.add_css_class("rec")
        self.b_rec.set_group(self.b_shot)
        self.b_shot.connect("toggled", lambda b: self._mode("screenshot", b))
        self.b_rec.connect("toggled", lambda b: self._mode("record", b))
        self.sep_rec = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.b_sys, self.img_sys = self._toggle("speaker", "System sound", "Record the sound your computer plays  (A)")
        self.b_mic, self.img_mic = self._toggle("mic", "Microphone", "Record your microphone  (V)")
        self.b_ptr, _ = self._toggle("pointer", "Mouse pointer", "Include the mouse pointer  (M)")
        self.sep_tail = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.b_window = self._button("window", "Window...", "Pick a window to capture or record")
        self.b_screen = self._button("screen", "This screen", "Capture or record this whole screen  (Enter)")
        for w in (self.b_shot, self.b_rec, self.sep_rec, self.b_sys, self.b_mic, self.b_ptr, self.sep_tail,
                  self.b_window, self.b_screen):
            self.append(w)
        self.b_sys.connect("toggled", lambda b: self._flag("system", b))
        self.b_mic.connect("toggled", lambda b: self._flag("mic", b))
        self.b_ptr.connect("toggled", lambda b: self._flag("cursor", b))
        self.b_window.connect("clicked", lambda *_: selector.pick_window())
        self.b_screen.connect("clicked", lambda *_: selector.pick_screen(self))
        self.sync()

    @staticmethod
    def _plain(btn, tip):
        btn.set_focusable(False)                  # keys (Enter, Esc, S, R...) must reach the overlay, not a button
        btn.set_focus_on_click(False)
        btn.set_tooltip_text(tip)
        return btn

    def _toggle(self, icon, text, tip):
        box, img = _icon_label(icon, text)
        btn = self._plain(Gtk.ToggleButton(), tip)
        btn.set_child(box)
        return btn, img

    def _button(self, icon, text, tip):
        box, _img = _icon_label(icon, text)
        btn = self._plain(Gtk.Button(), tip)
        btn.set_child(box)
        return btn

    def _mode(self, mode, btn):
        if not self._syncing and btn.get_active():
            self.selector.set_mode(mode)

    def _flag(self, key, btn):
        if not self._syncing:
            self.selector.set_flag(key, btn.get_active())

    def sync(self):
        """Show the selector's current state (called whenever it changes, from any monitor's toolbar)."""
        sel = self.selector
        rec = sel.mode == "record"
        self._syncing = True
        self.b_rec.set_active(rec)
        self.b_shot.set_active(not rec)
        self.b_sys.set_active(sel.rec["system"])
        self.b_mic.set_active(sel.rec["mic"])
        self.b_ptr.set_active(sel.cursor_on)
        self.img_sys.set_from_paintable(IC.texture(IC.UI["speaker" if sel.rec["system"] else "speaker-off"]))
        self.img_mic.set_from_paintable(IC.texture(IC.UI["mic" if sel.rec["mic"] else "mic-off"]))
        for w in (self.sep_rec, self.b_sys, self.b_mic):
            w.set_visible(rec)
        self._syncing = False


class _ArmBar(Gtk.Box):
    """Shown next to a chosen rectangle in record mode: the red Start button (Enter) and Cancel."""

    def __init__(self, selector):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add_css_class("snipshot-toolbar")
        self.add_css_class("snipshot-arm")
        start = Gtk.Button()
        start.add_css_class("start")
        box, _img = _icon_label("record", "Start recording")
        start.set_child(box)
        start.set_tooltip_text("Start recording this area  (Enter)")
        start.set_focusable(False)
        start.connect("clicked", lambda *_: selector.start_recording())
        cancel = Gtk.Button(label="Cancel")
        cancel.set_focusable(False)
        cancel.connect("clicked", lambda *_: selector.cancel())
        self.append(start)
        self.append(cancel)


class _MonitorWindow(Gtk.Window):
    def __init__(self, selector, shot, index):
        super().__init__(decorated=False)
        self.selector, self.shot, self.index = selector, shot, index
        i = shot.info
        self.mx, self.my, self.mw, self.mh = i.x, i.y, i.w, i.h
        self.nh, self.nw = shot.array.shape[:2]
        self.add_css_class("snipshot-overlay")
        self.area = _Canvas(self)
        overlay = Gtk.Overlay()
        overlay.set_child(self.area)
        self.set_child(overlay)
        self.toolbar = _Toolbar(selector)
        self.toolbar.set_halign(Gtk.Align.CENTER)
        self.toolbar.set_valign(Gtk.Align.START)
        self.toolbar.set_margin_top(10)
        overlay.add_overlay(self.toolbar)
        self.arm_bar = _ArmBar(selector)
        self.arm_bar.set_halign(Gtk.Align.START)
        self.arm_bar.set_valign(Gtk.Align.START)
        self.arm_bar.set_visible(False)
        overlay.add_overlay(self.arm_bar)
        self.texture = _texture(shot.array)               # the monitor's real pixels, shown 1:1 on that monitor
        drag = Gtk.GestureDrag(button=1)
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", self._end)
        self.area.add_controller(drag)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("enter", self._motion)
        self.area.add_controller(motion)
        right = Gtk.GestureClick(button=3)
        right.connect("pressed", lambda *_: selector.cancel())
        self.area.add_controller(right)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

    # coordinates: global logical <-> this monitor
    def _g(self, x, y):
        return self.mx + x, self.my + y

    def _clamp_to_anchor(self, gx, gy):
        a = self.selector.shared.windows[self.selector.shared.anchor]
        return min(max(gx, a.mx), a.mx + a.mw), min(max(gy, a.my), a.my + a.mh)

    def _begin(self, g, x, y):
        sh = self.selector.shared
        self.selector.disarm()
        sh.anchor = self.index
        sh.start = sh.cur = self._g(x, y)
        sh.redraw()

    def _update(self, g, dx, dy):
        sh = self.selector.shared
        if sh.start:
            ok, sx, sy = g.get_start_point()
            sh.cur = self._clamp_to_anchor(*self._g(sx + dx, sy + dy))
            sh.hover, sh.hover_win = sh.cur, sh.anchor
            sh.redraw([sh.anchor])                       # the selection lives on one monitor only

    def _end(self, g, dx, dy):
        sh = self.selector.shared
        if sh.start:
            ok, sx, sy = g.get_start_point()
            sh.cur = self._clamp_to_anchor(*self._g(sx + dx, sy + dy))
            self.selector.released(sh.rect(), sh.anchor)

    def _motion(self, _c, x, y):
        sh = self.selector.shared
        if not sh.start:
            previous = sh.hover_win
            sh.hover, sh.hover_win = self._g(x, y), self.index
            sh.redraw([self.index] if previous in (None, self.index) else [self.index, previous])

    def _key(self, _c, keyval, _code, _state):
        s = self.selector
        if keyval == Gdk.KEY_Escape:
            s.cancel()
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            s.enter(self.index)                  # Enter: start the armed recording, or take this whole monitor
        elif keyval in (Gdk.KEY_m, Gdk.KEY_M):
            s.set_flag("cursor", not s.cursor_on)
        elif keyval in (Gdk.KEY_r, Gdk.KEY_R):
            s.set_mode("record")
        elif keyval in (Gdk.KEY_s, Gdk.KEY_S):
            s.set_mode("screenshot")
        elif keyval in (Gdk.KEY_a, Gdk.KEY_A) and s.mode == "record":
            s.set_flag("system", not s.rec["system"])
        elif keyval in (Gdk.KEY_v, Gdk.KEY_V) and s.mode == "record":
            s.set_flag("mic", not s.rec["mic"])
        elif keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            s.zoomer = not s.zoomer
            s.shared.redraw()
        else:
            return False
        return True

    # drawing: only cheap GPU operations per frame
    def paint(self, widget, snap):
        self.paints = getattr(self, "paints", 0) + 1                 # counted only for the benchmark
        w, h = widget.get_width(), widget.get_height()
        sel = self.selector
        sh = sel.shared
        # LINEAR, not TRILINEAR: shown 1:1 so mipmaps add nothing, and they cost a third more GPU memory,
        # which matters because this desktop's GPU memory is nearly full.
        snap.append_scaled_texture(self.texture, Gsk.ScalingFilter.LINEAR, _rect(0, 0, w, h))
        rect = sh.rect()
        mine = sh.anchor is None or sh.anchor == self.index
        if rect and rect[2] >= 1 and rect[3] >= 1 and mine:
            lx, ly, rw, rh = rect[0] - self.mx, rect[1] - self.my, rect[2], rect[3]
            cx0, cy0 = max(0.0, lx), max(0.0, ly)
            cx1, cy1 = min(float(w), lx + rw), min(float(h), ly + rh)
            snap.append_color(DIM, _rect(0, 0, w, cy0))
            snap.append_color(DIM, _rect(0, cy1, w, h - cy1))
            snap.append_color(DIM, _rect(0, cy0, cx0, cy1 - cy0))
            snap.append_color(DIM, _rect(cx1, cy0, w - cx1, cy1 - cy0))
            outline = Gsk.RoundedRect()
            outline.init_from_rect(_rect(lx, ly, rw, rh), 0)
            line = LINE_REC if sel.mode == "record" else LINE
            snap.append_border(outline, [1.5] * 4, [line] * 4)
            _nx, _ny, nw_, nh_ = logical_to_native((lx, ly, rw, rh), self.shot.info, self.nw, self.nh)
            label = f"{nw_} x {nh_}" + ("  (recording area)" if sel.mode == "record" else "")
            self._pill(widget, snap, label, max(4.0, min(cx0, w - 120.0)), cy0 - 30 if cy0 > 34 else cy1 + 6)
        else:
            snap.append_color(DIM, _rect(0, 0, w, h))
            if sh.hover and sh.hover_win == self.index and sh.start is None:
                hx, hy = sh.hover[0] - self.mx, sh.hover[1] - self.my
                snap.append_color(CROSS, _rect(0, hy, w, 1))
                snap.append_color(CROSS, _rect(hx, 0, 1, h))
        if sh.hover and sh.hover_win == self.index and sel.zoomer and not sh.armed:
            self._loupe(snap, w, h, sh.hover[0] - self.mx, sh.hover[1] - self.my)
        if self.index == 0 and sh.start is None:
            cur = "on" if sel.cursor_on else "off"
            if sel.mode == "record":
                text = (f"Drag to choose what to record  -  Enter: this whole screen  -  A: system sound  -  "
                        f"V: microphone  -  M: mouse pointer ({cur})  -  Esc: cancel")
            else:
                text = (f"Drag to capture a region  -  Enter: this screen  -  M: mouse cursor ({cur})  -  "
                        f"Z: zoomer  -  Esc: cancel")
            self._pill(widget, snap, text, max(8.0, w / 2 - 330), 74)

    def _loupe(self, snap, w, h, px, py):
        """The zoomer: the real pixels around the pointer, magnified, with the centre pixel marked."""
        npx, npy = px * self.nw / max(self.mw, 1), py * self.nh / max(self.mh, 1)      # pointer in native pixels
        size = LOUPE_SIZE
        bx = px + 28 if px + 28 + size < w else px - 28 - size
        by = py + 28 if py + 28 + size < h else py - 28 - size
        box = _rect(bx, by, size, size)
        snap.append_color(LOUPE_BG, box)
        snap.push_clip(box)
        # draw the texture so the native pixel under the pointer lands in the middle of the box
        dest = _rect(bx + size / 2 - (int(npx) + 0.5) * LOUPE_PX, by + size / 2 - (int(npy) + 0.5) * LOUPE_PX,
                     self.nw * LOUPE_PX, self.nh * LOUPE_PX)
        snap.append_scaled_texture(self.texture, Gsk.ScalingFilter.NEAREST, dest)
        snap.pop()
        ring = Gsk.RoundedRect()
        ring.init_from_rect(_rect(bx + size / 2 - LOUPE_PX / 2, by + size / 2 - LOUPE_PX / 2, LOUPE_PX, LOUPE_PX), 0)
        snap.append_border(ring, [1] * 4, [LINE] * 4)
        frame = Gsk.RoundedRect()
        frame.init_from_rect(box, 0)
        snap.append_border(frame, [2] * 4, [WHITE] * 4)

    def _pill(self, widget, snap, text, x, y):
        layout = widget.create_pango_layout(None)
        layout.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>", -1)
        tw, th = layout.get_pixel_size()
        snap.append_color(PILL, _rect(x, y, tw + 16, th + 8))
        snap.save()
        snap.translate(_point(x + 8, y + 4))
        snap.append_layout(layout, WHITE)
        snap.restore()


class RegionSelector:
    """Shows every monitor's frozen frame; calls ``on_done(result or None)`` once.

    ``result`` is a dict: array (real pixels of the region), monitor (connector), region (x, y, w, h native),
    cursor ((sprite, x, y) relative to the region, if the cursor was inside and is included) and shot."""

    def __init__(self, shots, on_done, include_cursor=True, mode="screenshot", rec=None):
        self.shots = shots
        self.on_done = on_done
        self.include_cursor = include_cursor
        self.mode = mode if mode in ("screenshot", "record") else "screenshot"
        self.rec = dict(system=True, mic=False, cursor=True)       # recording options, edited in the toolbar
        self.rec.update(rec or {})
        self.zoomer = True
        self.shared = _Shared()
        self.finished = False
        by_connector = {m.get_connector(): i for i, m in enumerate(Gdk.Display.get_default().get_monitors())}
        self.monitor_index = {}
        for i, shot in enumerate(shots):
            win = _MonitorWindow(self, shot, i)
            self.shared.windows.append(win)
            self.monitor_index[i] = by_connector.get(shot.info.connector, i)
        self.sync_toolbars()

    # -- toolbar state
    @property
    def cursor_on(self):
        return self.rec["cursor"] if self.mode == "record" else self.include_cursor

    def sync_toolbars(self):
        for w in self.shared.windows:
            w.toolbar.sync()

    def set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        self.disarm()
        self.shared.start = self.shared.cur = None
        self.sync_toolbars()
        self.shared.redraw()

    def set_flag(self, key, value):
        if key == "cursor" and self.mode != "record":
            self.include_cursor = bool(value)
        else:
            self.rec[key] = bool(value)
        self.sync_toolbars()
        self.shared.redraw()

    # -- record mode: choose a rectangle, then press Start
    def released(self, rect, index):
        """The drag ended. Screenshots are taken at once; a recording waits for Start so the choice can be redone."""
        if self.mode == "record":
            if rect and rect[2] >= 16 and rect[3] >= 16:
                self.arm(rect, index)
            else:                                     # an accidental click: forget it and let them try again
                self.shared.start = self.shared.cur = None
                self.shared.redraw()
        else:
            self.finish(rect, index)

    def arm(self, rect, index):
        sh = self.shared
        sh.armed = True
        win = sh.windows[index]
        self.shared.redraw([index])
        for i, w in enumerate(sh.windows):
            w.arm_bar.set_visible(i == index)
        bar = win.arm_bar
        nat_w = bar.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        nat_h = bar.measure(Gtk.Orientation.VERTICAL, -1)[1]
        lx, ly = rect[0] - win.mx, rect[1] - win.my
        x = min(max(8.0, lx + rect[2] / 2 - nat_w / 2), max(8.0, win.mw - nat_w - 8))
        below = ly + rect[3] + 10
        y = below if below + nat_h < win.mh - 8 else (ly - nat_h - 10 if ly - nat_h - 10 > 70 else ly + rect[3] - nat_h - 10)
        bar.set_margin_start(int(x))
        bar.set_margin_top(int(max(70.0, y)))

    def disarm(self):
        self.shared.armed = False
        for w in self.shared.windows:
            w.arm_bar.set_visible(False)

    def start_recording(self):
        sh = self.shared
        if sh.armed and sh.rect():
            self.finish(sh.rect(), sh.anchor)

    def enter(self, index):
        if self.mode == "record" and self.shared.armed:
            return self.start_recording()
        win = self.shared.windows[index]
        self.finish((win.mx, win.my, win.mw, win.mh), index)

    def pick_screen(self, toolbar):
        for i, w in enumerate(self.shared.windows):
            if w.toolbar is toolbar:
                return self.finish((w.mx, w.my, w.mw, w.mh), i)

    def pick_window(self):
        self.finish(None, 0, target="window")

    def show(self):
        monitors = Gdk.Display.get_default().get_monitors()
        for i, win in enumerate(self.shared.windows):
            win.fullscreen_on_monitor(monitors.get_item(self.monitor_index[i]))
            win.present()
        if os.environ.get("SNIPSHOT_OVERLAY_BENCH"):
            self._bench()

    def _bench(self):
        """Developer check: sweep the pointer over each monitor in turn and report how many frames per second that
        monitor's overlay really painted while the pointer was on it."""
        import sys
        wins = self.shared.windows
        phase_s = 2.0
        t0 = time.time()
        marks, rates = {}, {}

        def step():
            now = time.time() - t0
            idx = min(int(now // phase_s), len(wins) - 1)
            if now >= phase_s * len(wins):
                print("[snipshot] overlay paints per second while the pointer is on each monitor:", rates,
                      file=sys.stderr, flush=True)
                self.cancel()
                return False
            w = wins[idx]
            if idx not in marks:
                marks[idx] = (now, getattr(w, "paints", 0))
            elif now - marks[idx][0] >= phase_s - 0.1 and w.shot.info.connector not in rates:
                rates[w.shot.info.connector] = round((getattr(w, "paints", 0) - marks[idx][1]) / (now - marks[idx][0]), 1)
            self.shared.hover = (w.mx + float((now * 1400) % w.mw), w.my + float((now * 500) % max(1, w.mh - 200) + 100))
            previous, self.shared.hover_win = self.shared.hover_win, idx
            self.shared.redraw([idx] if previous in (None, idx) else [idx, previous])
            return True
        GLib.timeout_add(8, step)

    def _close(self):
        for w in self.shared.windows:
            w.destroy()
        self.shared.windows = []

    def cancel(self):
        if not self.finished:
            self.finished = True
            self._close()
            self.on_done(None)

    def finish(self, logical_rect, index, target=None):
        """End the selection. ``on_done`` gets None (cancelled) or a dict with "mode" ("screenshot" or "record"),
        "target" ("region", "screen" or "window"), "monitor", "shot", "opts" (the record options) and, for
        screenshots, "array", "region" (real pixels) and "cursor"."""
        if self.finished:
            return
        self.finished = True
        win = self.shared.windows[index]
        shot = win.shot
        mode, opts = self.mode, dict(self.rec)
        self._close()
        if target == "window":
            self.on_done(dict(mode=mode, target="window", monitor=shot.info.connector, shot=shot, opts=opts))
            return
        if not logical_rect or logical_rect[2] < 3 or logical_rect[3] < 3:
            self.on_done(None)
            return
        local = (logical_rect[0] - shot.info.x, logical_rect[1] - shot.info.y, logical_rect[2], logical_rect[3])
        h, w = shot.array.shape[:2]
        x, y, rw, rh = logical_to_native(local, shot.info, w, h)
        if rw < 2 or rh < 2:
            self.on_done(None)
            return
        region = (x, y, rw, rh)
        if mode == "record":
            whole = (x, y, rw, rh) == (0, 0, w, h)
            self.on_done(dict(mode="record", target="screen" if whole else "region", monitor=shot.info.connector,
                              region=region, opts=opts, shot=shot))
            return
        self.on_done(dict(mode="screenshot", target="region", array=shot.array[y:y + rh, x:x + rw].copy(),
                          monitor=shot.info.connector, region=region, opts=opts, shot=shot,
                          cursor=cursor_in_region(shot, region) if self.include_cursor else None))
