"""The editing surface: shows a Scene, lets you draw, select, move, resize, edit text, crop, zoom, undo.

Behaviour follows Greenshot: drawing tools return to the selection tool after one object, Shift constrains,
Ctrl draws from the centre, double-click edits text, handles resize, step labels renumber automatically.
"""
import copy
import math
import time

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, Gio, GLib, Graphene, Gtk  # noqa: E402

import imaging as im  # noqa: E402
import model as M  # noqa: E402
import render as R  # noqa: E402

TOOLS = ("select", "rect", "ellipse", "line", "arrow", "freehand", "text", "speech", "step", "obfuscate",
         "highlight", "crop")
DRAW_KINDS = {"rect": "rect", "ellipse": "ellipse", "line": "line", "arrow": "arrow", "freehand": "freehand",
              "text": "text", "speech": "speech", "step": "step", "obfuscate": "obfuscate", "highlight": "highlight"}
MARGIN = 24
HANDLE = 2.0                      # half size of a handle square in screen px: 4px squares
HANDLE_GAP = 2.0                  # space between an object's edge and its handles: they sit OUTSIDE the object
HANDLE_HIT = 6.0                  # grab tolerance in screen px (drawn small, but still easy to hit)
SELECT_GAP = 1.5                  # the dashed selection outline sits this far outside the object
ZOOM_NOTCH = 1.25                 # Ctrl + wheel: zoom factor per notch
ZOOM_MIN, ZOOM_MAX = 0.05, 16.0
ZOOM_STEPS = (0.25, 0.5, 0.66, 0.75, 1.0, 2.0, 3.0, 4.0, 6.0)

_object_clipboard = []            # shared by all editor windows: Ctrl+C / Ctrl+V of annotations


class Canvas(Gtk.ScrolledWindow):
    def __init__(self, scene, config=None):
        super().__init__()
        self.scene = scene
        self.cfg = config or {}
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.zoom = 1.0
        self.fit = True
        self.tool = "select"
        self.selection = []
        self.crop = None                       # a transient 'crop' Obj, not part of the scene
        self.undo_stack, self.redo_stack = [], []
        self.defaults = {k: copy.deepcopy(v) for k, v in M.DEFAULTS.items()}
        self.defaults["obfuscate"].update(
            pixel_size=int(self.cfg.get("obfuscate_pixel_size", 10)),
            blur_radius=int(self.cfg.get("obfuscate_blur_radius", 10)),
            randomise=bool(self.cfg.get("obfuscate_randomise", False)))
        self.on_changed = lambda: None          # scene content changed (title/dirty state)
        self.on_selection = lambda: None        # selection or tool changed (property bar refresh)
        self.on_tool_done = lambda: None        # a drawing tool finished one object -> back to select
        self.on_status = lambda text: None
        self.on_zoom = lambda z: None
        self.on_size = lambda: None             # image dimensions changed (crop, rotate, ...)
        self.modified = False
        self._gesture = None
        self._cache = (None, None)
        self._has_alpha = False
        self._alpha_for = None
        self._edit = None                       # active in-place text edit
        self._pointer = (0, 0)
        self._pointer_widget = (0, 0)
        self._hover = False
        self._scroll_accum = 0.0
        self._pointer_override = None          # tests: pretend the pointer is here (viewport coordinates)
        self._zoom_anchor = None               # (image x, image y, viewport x, viewport y, expiry time)

        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self._draw)
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        self.area.set_focusable(True)
        self.overlay = Gtk.Overlay()
        self.overlay.set_child(self.area)
        self.set_child(self.overlay)
        viewport = self.get_child()
        if isinstance(viewport, Gtk.Viewport):
            viewport.set_scroll_to_focus(False)        # GTK would otherwise scroll when focus moves (random jolts)

        drag = Gtk.GestureDrag(button=1)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.area.add_controller(drag)
        click = Gtk.GestureClick(button=1)
        click.connect("pressed", self._click)
        self.area.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("enter", self._motion)
        motion.connect("leave", lambda *_: (self.on_status(""), setattr(self, "_hover", False)))
        self.area.add_controller(motion)
        right = Gtk.GestureClick(button=3)
        right.connect("pressed", self._right_click)
        self.area.add_controller(right)
        self._ctx_group = Gio.SimpleActionGroup()
        self.area.insert_action_group("ctx", self._ctx_group)
        self._ctx_popover = None
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._scroll)
        scroll.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.area.add_controller(scroll)

        provider = Gtk.CssProvider()
        self._text_css = provider
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.connect("notify::width", lambda *_: self._maybe_refit())
        self.connect("notify::height", lambda *_: self._maybe_refit())
        self._update_size()

    # ------------------------------------------------------------------ geometry
    def _page(self):
        """Size of the visible part of the scrolled view."""
        h, v = self.get_hadjustment(), self.get_vadjustment()
        return (h.get_page_size() or self.get_width() or 1), (v.get_page_size() or self.get_height() or 1)

    def _area_size(self):
        """Size the drawing area will have once laid out: big enough for the picture, at least as big as the
        view. Computed here instead of read from the widget, because the widget only learns its new size a
        frame after a zoom change, and reading the stale size is what made the picture jolt."""
        iw, ih = self.scene.size
        pw, ph = self._page()
        return max(int(iw * self.zoom) + 2 * MARGIN, pw), max(int(ih * self.zoom) + 2 * MARGIN, ph)

    def _origin(self):
        iw, ih = self.scene.size
        aw, ah = self._area_size()
        return max(MARGIN, (aw - iw * self.zoom) / 2), max(MARGIN, (ah - ih * self.zoom) / 2)

    def to_img(self, wx, wy):
        ox, oy = self._origin()
        return (wx - ox) / self.zoom, (wy - oy) / self.zoom

    def to_widget(self, ix, iy):
        ox, oy = self._origin()
        return ix * self.zoom + ox, iy * self.zoom + oy

    def _update_size(self):
        iw, ih = self.scene.size
        self.area.set_content_width(int(iw * self.zoom) + 2 * MARGIN)
        self.area.set_content_height(int(ih * self.zoom) + 2 * MARGIN)
        self.area.queue_draw()

    def set_zoom(self, z, fit=False):
        self.fit = fit
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, z))
        self._update_size()
        self.on_zoom(self.zoom)

    def zoom_fit(self):
        iw, ih = self.scene.size
        vw, vh = max(50, self.get_width() - 2 * MARGIN), max(50, self.get_height() - 2 * MARGIN)
        self.set_zoom(min(1.0, vw / iw, vh / ih) if self.get_width() > 1 else 1.0, fit=True)

    def _maybe_refit(self):
        if self.fit:
            self.zoom_fit()

    def zoom_in(self):
        nxt = next((s for s in ZOOM_STEPS if s > self.zoom + 1e-6), ZOOM_MAX)
        self.set_zoom(nxt)

    def zoom_out(self):
        prv = next((s for s in reversed(ZOOM_STEPS) if s < self.zoom - 1e-6), ZOOM_MIN)
        self.set_zoom(prv)

    def _scroll(self, ctrl, dx, dy):
        if ctrl.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            return self.handle_ctrl_scroll(dy)
        return False

    def pointer_view(self):
        """(x, y) of the mouse pointer inside the scrolled view, or None when it is not over it. Asks the
        windowing system directly, so it is right even if the mouse has not moved since the window appeared."""
        if self._pointer_override is not None:
            return self._pointer_override
        try:
            native = self.get_native()
            surface = native.get_surface()
            device = self.get_display().get_default_seat().get_pointer()
            ok, sx, sy, _mask = surface.get_device_position(device)
            if ok:
                tx, ty = native.get_surface_transform()
                point = Graphene.Point()
                point.init(sx - tx, sy - ty)
                found, p = native.compute_point(self, point)
                if found and 0 <= p.x <= self.get_width() and 0 <= p.y <= self.get_height():
                    return p.x, p.y
                return None
        except (AttributeError, TypeError):
            pass
        if self._hover:                                  # fall back to the last position we saw
            wx, wy = self._pointer_widget
            return wx - self.get_hadjustment().get_value(), wy - self.get_vadjustment().get_value()
        return None

    def pointer_over(self):
        return self.pointer_view() is not None

    def handle_ctrl_scroll(self, dy):
        """Ctrl + mouse wheel: zoom in or out around the pointer. Small trackpad scrolls add up to a full notch."""
        self._scroll_accum += -dy                         # wheel up (negative dy) zooms in
        steps = int(self._scroll_accum)
        if steps == 0:
            return True
        self._scroll_accum -= steps
        for _ in range(abs(steps)):
            self.zoom_step_at(1 if steps > 0 else -1)
        return True

    def zoom_step_at(self, direction):
        """One zoom notch that keeps the picture point under the pointer fixed on screen.

        Everything is computed from the zoom, the picture size and the view size (never from widget sizes that
        lag a frame behind), and the scroll position is set directly, so there is no intermediate frame where the
        picture is in the wrong place. For several notches in a row, or while the mouse only jitters a few
        pixels, the original anchor point is kept so rounding never accumulates."""
        h, v = self.get_hadjustment(), self.get_vadjustment()
        pw, ph = self._page()
        now = time.monotonic()
        view = self.pointer_view()
        if view is None:
            view = (pw / 2, ph / 2)                        # pointer not over the picture: zoom around the middle
        g = self._zoom_anchor
        if g is not None and now < g[4] and abs(view[0] - g[2]) < 6 and abs(view[1] - g[3]) < 6:
            ix, iy, vx, vy = g[:4]
        else:
            vx, vy = view
            ox, oy = self._origin()
            ix, iy = (vx + h.get_value() - ox) / self.zoom, (vy + v.get_value() - oy) / self.zoom
        before = self.zoom
        self.set_zoom(self.zoom * (ZOOM_NOTCH if direction > 0 else 1 / ZOOM_NOTCH))
        if self.zoom == before:
            return
        ix, iy = self._place_view(ix, iy, vx, vy)
        self._zoom_anchor = (ix, iy, vx, vy, now + 0.4)

    def _place_view(self, ix, iy, vx, vy):
        """Scroll so picture point (ix, iy) appears at view position (vx, vy), as far as the scroll range allows.
        Returns the picture point that really ends up there. When the range forces the picture to move (for
        instance it is smaller than the window and centred), the anchor must become that point: restoring the
        original one on the next notch would make the picture jump to somewhere you are not pointing."""
        h, v = self.get_hadjustment(), self.get_vadjustment()
        aw, ah = self._area_size()
        pw, ph = self._page()
        ox, oy = self._origin()
        want_x, want_y = ox + ix * self.zoom - vx, oy + iy * self.zoom - vy
        sx = min(max(want_x, 0.0), max(0.0, aw - pw))
        sy = min(max(want_y, 0.0), max(0.0, ah - ph))
        if abs(sx - want_x) > 0.5:
            ix = (vx + sx - ox) / self.zoom
        if abs(sy - want_y) > 0.5:
            iy = (vy + sy - oy) / self.zoom
        # configure() sets range and position together, so the position is not clamped to the old, smaller range
        h.configure(sx, 0.0, float(aw), h.get_step_increment(), h.get_page_increment(), float(pw))
        v.configure(sy, 0.0, float(ah), v.get_step_increment(), v.get_page_increment(), float(ph))
        return ix, iy

    # ------------------------------------------------------------------ rendering
    def rendered(self):
        hide = (self._edit["obj"].uid,) if self._edit else ()
        key = (self.scene.version, hide)
        if self._cache[0] != key:
            self._cache = (key, R.render_scene(self.scene, hide=set(hide)))
        return self._cache[1]

    def export_array(self):
        self._finish_text_edit()
        return im.from_surface(R.render_scene(self.scene))

    def _alpha_check(self):
        if self._alpha_for is not self.scene.base:
            self._has_alpha = bool((self.scene.base[..., 3] < 255).any())
            self._alpha_for = self.scene.base
        return self._has_alpha

    def _draw(self, _area, cr, w, h):
        cr.set_source_rgb(0.40, 0.42, 0.45)
        cr.paint()
        iw, ih = self.scene.size
        ox, oy = self._origin()
        cr.save()
        cr.translate(ox, oy)
        cr.scale(self.zoom, self.zoom)
        if self._alpha_check():
            self._checker(cr, iw, ih)
        surf = self.rendered()
        cr.set_source_surface(surf, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST if self.zoom >= 2 else cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()
        # image frame
        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.set_line_width(1)
        cr.rectangle(ox - 0.5, oy - 0.5, iw * self.zoom + 1, ih * self.zoom + 1)
        cr.stroke()
        self._draw_crop(cr)
        for o in self.selection:
            self._draw_selection(cr, o)
        g = self._gesture
        if g and g["kind"] == "rubber":
            self._dashed_rect(cr, g["rect"], (0.2, 0.5, 1, 1))

    def _checker(self, cr, iw, ih):
        cr.save()
        cr.rectangle(0, 0, iw, ih)
        cr.clip()
        s = 8 / max(self.zoom, 0.01)
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.set_source_rgb(0.8, 0.8, 0.8)
        for y in range(int(ih / s) + 1):
            for x in range(int(iw / s) + 1):
                if (x + y) % 2:
                    cr.rectangle(x * s, y * s, s, s)
        cr.fill()
        cr.restore()

    def _dashed_rect(self, cr, rect_img, rgba):
        x, y, w, h = rect_img
        wx, wy = self.to_widget(x, y)
        cr.save()
        cr.set_source_rgba(*rgba)
        cr.set_line_width(1)
        cr.set_dash([4, 3])
        cr.rectangle(wx + 0.5, wy + 0.5, w * self.zoom, h * self.zoom)
        cr.stroke()
        cr.restore()

    def _handle_points(self, o):
        """[(name, x, y)] screen positions of an object's handles. Box handles are pushed outward by half their
        size plus a gap so they never cover the object's own pixels; line end points stay on the end."""
        out = []
        off = HANDLE + HANDLE_GAP
        for name, hx, hy in M.handles(o):
            wx, wy = self.to_widget(hx, hy)
            if name not in ("start", "end", "tail"):
                wx += off * (1 if "e" in name else -1 if "w" in name else 0)
                wy += off * (1 if "s" in name else -1 if "n" in name else 0)
            out.append((name, wx, wy))
        return out

    def _handle_at(self, o, ix, iy):
        """Name of the handle under the image point (ix, iy), or None. Uses screen distances, so the grab area
        stays the same at any zoom."""
        px, py = self.to_widget(ix, iy)
        for name, wx, wy in reversed(self._handle_points(o)):
            if abs(px - wx) <= HANDLE_HIT and abs(py - wy) <= HANDLE_HIT:
                return name
        return None

    def _draw_handles(self, cr, o):
        for _name, wx, wy in self._handle_points(o):
            x, y = round(wx - HANDLE), round(wy - HANDLE)
            cr.rectangle(x, y, 2 * HANDLE, 2 * HANDLE)
            cr.set_source_rgb(1, 1, 1)
            cr.fill()
            cr.rectangle(x + 0.5, y + 0.5, 2 * HANDLE - 1, 2 * HANDLE - 1)
            cr.set_source_rgb(0.1, 0.1, 0.1)
            cr.set_line_width(1)
            cr.stroke()

    def _select_outline(self, cr, rect_img, rgba):
        """Dashed selection outline drawn just OUTSIDE the object so it never sits on top of its pixels."""
        x, y, w, h = rect_img
        wx, wy = self.to_widget(x, y)
        cr.save()
        cr.set_source_rgba(*rgba)
        cr.set_line_width(1)
        cr.set_dash([3, 2])
        cr.rectangle(wx - SELECT_GAP + 0.5, wy - SELECT_GAP + 0.5, w * self.zoom + 2 * SELECT_GAP - 1,
                     h * self.zoom + 2 * SELECT_GAP - 1)
        cr.stroke()
        cr.restore()

    def _draw_selection(self, cr, o):
        if o.kind not in M.LINE_LIKE and o.kind != "freehand":
            self._select_outline(cr, o.rect(), (0.2, 0.5, 1, 0.9))
        elif o.kind == "freehand" and o.points:
            xs, ys = [p[0] for p in o.points], [p[1] for p in o.points]
            self._select_outline(cr, (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)), (0.2, 0.5, 1, 0.9))
        if len(self.selection) == 1:
            self._draw_handles(cr, o)

    def _draw_crop(self, cr):
        c = self.crop
        if not c:
            return
        iw, ih = self.scene.size
        x, y, w, h = c.rect()
        ox, oy = self._origin()
        cr.save()
        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.rectangle(ox, oy, iw * self.zoom, ih * self.zoom)
        wx, wy = self.to_widget(x, y)
        if c.p.get("mode") == "vertical":
            cr.rectangle(wx, oy, w * self.zoom, ih * self.zoom)
        elif c.p.get("mode") == "horizontal":
            cr.rectangle(ox, wy, iw * self.zoom, h * self.zoom)
        else:
            cr.rectangle(wx, wy, w * self.zoom, h * self.zoom)
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.fill()
        cr.restore()
        self._dashed_rect(cr, c.rect(), (1, 1, 1, 1))
        self._draw_handles(cr, c)

    # ------------------------------------------------------------------ undo
    def _push_undo(self, snap=None):
        self.undo_stack.append(snap or self.scene.snapshot())
        del self.undo_stack[:-100]
        self.redo_stack.clear()
        self.modified = True
        self.on_changed()

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self):
        self._finish_text_edit()
        if not self.undo_stack:
            return
        self.redo_stack.append(self.scene.snapshot())
        self._restore(self.undo_stack.pop())

    def redo(self):
        self._finish_text_edit()
        if not self.redo_stack:
            return
        self.undo_stack.append(self.scene.snapshot())
        self._restore(self.redo_stack.pop())

    def _restore(self, snap):
        ids = {o.uid for o in self.selection}
        old_size = self.scene.size
        self.scene.restore(snap)
        self.selection = [o for o in self.scene.objects if o.uid in ids]
        self.modified = True
        if old_size != self.scene.size:
            self._update_size()
            self._maybe_refit()
            self.on_size()
        self.on_changed()
        self.on_selection()
        self.area.queue_draw()

    def _changed(self):
        self.scene.touch()
        self.area.queue_draw()
        self.on_changed()

    # ------------------------------------------------------------------ tools & selection
    def set_tool(self, tool):
        self._finish_text_edit()
        if tool != "crop":
            self.crop = None
        if tool != "select":
            self.selection = []
        self.tool = tool
        self.area.set_cursor_from_name("default" if tool == "select" else "crosshair")
        self.on_selection()
        self.area.queue_draw()

    def select(self, objs):
        self.selection = list(objs)
        self.on_selection()
        self.area.queue_draw()

    def select_all(self):
        self.select([o for o in self.scene.objects])

    def selected_kinds(self):
        return {o.kind for o in self.selection} or ({DRAW_KINDS[self.tool]} if self.tool in DRAW_KINDS else set())

    def get_prop(self, name, default=None):
        if self.selection:
            for o in self.selection:
                if name in o.p:
                    return o.p[name]
        kind = DRAW_KINDS.get(self.tool)
        if kind and name in self.defaults[kind]:
            return self.defaults[kind][name]
        return default

    def set_prop(self, name, value):
        """Apply a property to the selection (if any) and remember it as the default for those kinds."""
        targets = [o for o in self.selection if name in o.p or name in self.defaults[o.kind]]
        kinds = {o.kind for o in targets}
        if not targets and self.tool in DRAW_KINDS:
            kinds = {DRAW_KINDS[self.tool]}
        for k in kinds:
            if name in self.defaults[k] or targets:
                self.defaults[k][name] = value
        if targets:
            self._push_undo()
            for o in targets:
                o.p[name] = value
            self._changed()
        if self.crop is not None and name == "mode":
            self.crop.p["mode"] = value
            self.area.queue_draw()

    # ------------------------------------------------------------------ gestures
    def _mods(self, g):
        s = g.get_current_event_state()
        return bool(s & Gdk.ModifierType.SHIFT_MASK), bool(s & Gdk.ModifierType.CONTROL_MASK)

    def _tol(self):
        return 5.0 / self.zoom

    def _drag_begin(self, g, x, y):
        self.area.grab_focus()
        self._finish_text_edit()
        shift, ctrl = self._mods(g)
        ix, iy = self.to_img(x, y)
        self._pointer = (ix, iy)
        if self.tool == "crop":
            self._begin_crop(ix, iy)
        elif self.tool != "select":
            if len(self.selection) == 1:
                name = self._handle_at(self.selection[0], ix, iy)
                if name:
                    self._gesture = dict(kind="resize", obj=self.selection[0], handle=name, snap=self.scene.snapshot(),
                                         dirty=False)
                    return
            self.selection = []
            self.on_selection()
            self._begin_create(ix, iy)
        else:
            self._begin_select(ix, iy, ctrl, shift)

    def _begin_select(self, ix, iy, ctrl, shift):
        if len(self.selection) == 1:
            o = self.selection[0]
            name = self._handle_at(o, ix, iy)
            if name:
                self._gesture = dict(kind="resize", obj=o, handle=name, snap=self.scene.snapshot(), dirty=False)
                return
        hit = self.scene.top_hit(ix, iy, self._tol())
        if hit is not None:
            if ctrl or shift:
                self.selection = [o for o in self.selection if o is not hit] if hit in self.selection else self.selection + [hit]
            elif hit not in self.selection:
                self.selection = [hit]
            self.on_selection()
            self._gesture = dict(kind="move", last=(ix, iy), snap=self.scene.snapshot(), dirty=False)
        else:
            if not (ctrl or shift):
                self.selection = []
                self.on_selection()
            self._gesture = dict(kind="rubber", start=(ix, iy), rect=(ix, iy, 0, 0), base=list(self.selection))
        self.area.queue_draw()

    def _begin_create(self, ix, iy):
        kind = DRAW_KINDS[self.tool]
        o = M.new_obj(kind, ix, iy)
        o.p.update(copy.deepcopy(self.defaults[kind]))
        snap = self.scene.snapshot()
        self.scene.add(o)
        self._gesture = dict(kind="create", obj=o, start=(ix, iy), snap=snap, dirty=True)
        if kind == "step":
            side = M.DEFAULT_SIZE["step"][0]
            o.set_rect(ix - side / 2, iy - side / 2, side, side)
        self.area.queue_draw()

    def _begin_crop(self, ix, iy):
        if self.crop is not None:
            name = self._handle_at(self.crop, ix, iy)
            x, y, w, h = self.crop.rect()
            if name:
                self._gesture = dict(kind="crop-resize", handle=name)
                return
            if x <= ix <= x + w and y <= iy <= y + h:
                self._gesture = dict(kind="crop-move", last=(ix, iy))
                return
        mode = self.crop.p.get("mode", "default") if self.crop else self.defaults["crop"].get("mode", "default")
        self.crop = M.new_obj("crop", ix, iy, mode=mode)
        self._gesture = dict(kind="crop-new", start=(ix, iy))
        self.on_selection()

    def _drag_update(self, g, dx, dy):
        gest = self._gesture
        if not gest:
            return
        ok, sx, sy = g.get_start_point()
        ix, iy = self.to_img(sx + dx, sy + dy)
        self._pointer = (ix, iy)
        shift, ctrl = self._mods(g)
        kind = gest["kind"]
        if kind == "move":
            ddx, ddy = ix - gest["last"][0], iy - gest["last"][1]
            if ddx or ddy:
                if not gest.get("moved"):
                    gest["moved"] = True
                for o in self.selection:
                    o.translate(ddx, ddy)
                gest["last"] = (ix, iy)
                gest["dirty"] = True
                self._changed_live()
        elif kind == "resize":
            M.drag_handle(gest["obj"], gest["handle"], ix, iy, keep_square=shift)
            if gest["obj"].kind in ("text", "speech"):
                gest["obj"].p["autosize"] = False
            gest["dirty"] = True
            self._changed_live()
        elif kind == "create":
            self._update_create(gest, ix, iy, shift, ctrl)
        elif kind == "rubber":
            sx0, sy0 = gest["start"]
            rect = (min(sx0, ix), min(sy0, iy), abs(ix - sx0), abs(iy - sy0))
            gest["rect"] = rect
            inside = [o for o in self.scene.objects if o.kind != "crop" and self._intersects(o, rect)]
            self.selection = list(dict.fromkeys(gest["base"] + inside))
            self.on_selection()
            self.area.queue_draw()
        elif kind in ("crop-new", "crop-resize", "crop-move"):
            self._update_crop(gest, ix, iy, shift)

    def _intersects(self, o, r):
        x, y, w, h = o.rect()
        if o.kind == "freehand" and o.points:
            xs, ys = [p[0] for p in o.points], [p[1] for p in o.points]
            x, y, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        return not (x > r[0] + r[2] or x + w < r[0] or y > r[1] + r[3] or y + h < r[1])

    def _changed_live(self):
        self.scene.touch()
        self.area.queue_draw()

    def _update_create(self, gest, ix, iy, shift, ctrl):
        o = gest["obj"]
        sx, sy = gest["start"]
        if o.kind == "freehand":
            if shift and o.points:
                ix, iy = M.constrain_end("line", *o.points[0], ix, iy)
            o.points.append((ix, iy))
        elif o.kind == "step":
            o.set_rect(ix - o.rect()[2] / 2, iy - o.rect()[3] / 2, o.rect()[2], o.rect()[3])
        else:
            if shift:
                ix, iy = M.constrain_end(o.kind, sx, sy, ix, iy)
            if ctrl and o.kind not in M.LINE_LIKE:
                o.x1, o.y1, o.x2, o.y2 = 2 * sx - ix, 2 * sy - iy, ix, iy
            else:
                o.x1, o.y1, o.x2, o.y2 = sx, sy, ix, iy
        self._changed_live()

    def _update_crop(self, gest, ix, iy, shift):
        iw, ih = self.scene.size
        ix, iy = max(0, min(iw, ix)), max(0, min(ih, iy))
        c = self.crop
        if gest["kind"] == "crop-new":
            sx, sy = gest["start"]
            sx, sy = max(0, min(iw, sx)), max(0, min(ih, sy))
            c.x1, c.y1, c.x2, c.y2 = sx, sy, ix, iy
        elif gest["kind"] == "crop-resize":
            M.drag_handle(c, gest["handle"], ix, iy)
        else:
            x, y, w, h = c.rect()
            dx, dy = ix - gest["last"][0], iy - gest["last"][1]
            nx, ny = max(0, min(iw - w, x + dx)), max(0, min(ih - h, y + dy))
            c.set_rect(nx, ny, w, h)
            gest["last"] = (ix, iy)
        mode = c.p.get("mode")
        if mode == "vertical":
            c.y1, c.y2 = 0, ih
        elif mode == "horizontal":
            c.x1, c.x2 = 0, iw
        self.area.queue_draw()
        self.on_status(f"Crop {int(c.rect()[2])} x {int(c.rect()[3])}")

    def _drag_end(self, g, dx, dy):
        gest, self._gesture = self._gesture, None
        if not gest:
            return
        kind = gest["kind"]
        if kind == "create":
            self._end_create(gest)
        elif kind in ("move", "resize"):
            if gest.get("dirty"):
                self._push_undo(gest["snap"])
        elif kind == "rubber":
            self.on_selection()
        elif kind.startswith("crop"):
            if self.crop is not None and self.crop.rect()[2] < 2 and self.crop.rect()[3] < 2:
                self.crop = None
            self.on_selection()
        self.area.queue_draw()

    def _end_create(self, gest):
        o = gest["obj"]
        snap = gest["snap"]
        x, y, w, h = o.rect()
        if o.kind == "text" and w < 8 and h < 8:
            o.p["autosize"] = True
            fw, fh = R.fit_text_size(o, " ")
            o.set_rect(x, y, fw, fh)
        elif o.kind == "speech" and w < 8 and h < 8:
            o.set_rect(x, y, 160, 70)
        elif o.is_empty(3) and o.kind not in ("step", "freehand"):
            self.scene.remove(o)
            return
        elif o.kind == "freehand" and len(o.points) < 2:
            self.scene.remove(o)
            return
        if o.kind == "speech":
            x, y, w, h = o.rect()
            o.tail = (x + w * 0.25, y + h + max(32.0, h * 0.6))
        if o.kind == "step":
            pass
        self._push_undo(snap)
        self.selection = [o]                       # the new object is selected, but the tool stays active
        self.scene.touch()
        self.on_selection()
        if o.kind in ("text", "speech"):
            self.begin_text_edit(o, is_new=True)

    # ------------------------------------------------------------------ click / hover
    def _click(self, g, n_press, x, y):
        if n_press == 2 and self.tool == "select":
            ix, iy = self.to_img(x, y)
            hit = self.scene.top_hit(ix, iy, self._tol())
            if hit is not None and hit.kind in ("text", "speech"):
                self.selection = [hit]
                self.on_selection()
                self.begin_text_edit(hit)

    def _motion(self, _c, x, y):
        ix, iy = self.to_img(x, y)
        self._pointer = (ix, iy)
        self._pointer_widget = (x, y)
        self._hover = True
        iw, ih = self.scene.size
        self.on_status(f"{int(ix)}, {int(iy)}" if 0 <= ix < iw and 0 <= iy < ih else "")
        if self._gesture:
            return
        if self.tool != "select":
            if self.tool != "crop" and len(self.selection) == 1:
                hname = self._handle_at(self.selection[0], ix, iy)
                self.area.set_cursor_from_name(M.HANDLE_CURSOR.get(hname, "crosshair") if hname else "crosshair")
            return
        name = None
        if len(self.selection) == 1:
            name = self._handle_at(self.selection[0], ix, iy)
        if name:
            cur = M.HANDLE_CURSOR.get(name, "default")
        elif self.scene.top_hit(ix, iy, self._tol()) is not None:
            cur = "move"
        else:
            cur = "default"
        self.area.set_cursor_from_name(cur)

    # ------------------------------------------------------------------ right-click menu (Greenshot's object menu)
    def _right_click(self, gesture, n_press, x, y):
        if self.tool == "crop":
            return
        ix, iy = self.to_img(x, y)
        hit = self.scene.top_hit(ix, iy, self._tol())
        if hit is not None and hit not in self.selection:
            self.selection = [hit]
            self.on_selection()
            self.area.queue_draw()
        if not self.selection:
            return                                   # nothing under the pointer and nothing selected: no menu
        self._finish_text_edit()
        self.show_context_menu(x, y)

    def context_menu_model(self):
        """The menu for the current selection: layer order, duplicate/copy/cut, expand / stretch / dock, delete,
        reset size. A mouse cursor only gets layer order and delete, because it is only ever moved."""
        sel, objs = self.selection, self.scene.objects
        idx = [objs.index(o) for o in sel if o in objs]
        menu = Gio.Menu()
        if not idx:
            return menu
        only_cursor = all(M.is_cursor(o) for o in sel)
        order = Gio.Menu()
        if max(idx) < len(objs) - 1 or len(idx) < len(objs) and max(idx) != len(objs) - 1:
            order.append("Up to top", "ctx.top")
            order.append("Up one level", "ctx.up")
        if min(idx) > 0:
            order.append("Down to bottom", "ctx.bottom")
            order.append("Down one level", "ctx.down")
        if order.get_n_items():
            menu.append_section(None, order)
        if not only_cursor:
            copy = Gio.Menu()
            copy.append("Duplicate selected element", "ctx.duplicate")
            copy.append("Copy", "ctx.copy")
            copy.append("Cut", "ctx.cut")
            menu.append_section(None, copy)
            place = Gio.Menu()
            for title, prefix in (("Expand capture and move outside", "push"), ("Stretch", "fit"), ("Dock to edge", "snap")):
                sub_m = Gio.Menu()
                labels = (("Width", "width"), ("Height", "height")) if prefix == "fit" else (
                    ("Top", "top"), ("Right", "right"), ("Bottom", "bottom"), ("Left", "left"))
                for label, key in labels:
                    sub_m.append(label, f"ctx.{prefix}_{key}")
                place.append_submenu(title, sub_m)
            menu.append_section(None, place)
        tail = Gio.Menu()
        tail.append("Delete", "ctx.delete")
        if not only_cursor and any(self._default_size(o) for o in sel):
            tail.append("Reset size", "ctx.reset")
        menu.append_section(None, tail)
        return menu

    @staticmethod
    def menu_labels(menu):
        """Flat list of the item labels in a Gio.Menu (submenu items are prefixed with their parent), for tests."""
        out = []
        for i in range(menu.get_n_items()):
            label = menu.get_item_attribute_value(i, "label")
            link_s, link_m = menu.get_item_link(i, "section"), menu.get_item_link(i, "submenu")
            if link_s is not None:
                out += Canvas.menu_labels(link_s)
            elif link_m is not None:
                out += [f"{label.get_string()} > {x}" for x in Canvas.menu_labels(link_m)]
            elif label is not None:
                out.append(label.get_string())
        return out

    def _install_ctx_actions(self):
        for name in list(self._ctx_group.list_actions()):
            self._ctx_group.remove_action(name)

        def add(name, fn):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda *_: fn())
            self._ctx_group.add_action(act)
        add("top", lambda: self.arrange("front"))
        add("up", lambda: self.arrange("up"))
        add("down", lambda: self.arrange("down"))
        add("bottom", lambda: self.arrange("back"))
        add("duplicate", self.duplicate_selected)
        add("copy", self.copy_selected)
        add("cut", self.cut_selected)
        add("delete", self.delete_selected)
        add("reset", self.reset_size)
        for d in ("top", "right", "bottom", "left"):
            add(f"push_{d}", lambda d=d: self.push_out(d))
            add(f"snap_{d}", lambda d=d: self.snap_to_edge(d))
        add("fit_width", lambda: self.fit_to_image("width"))
        add("fit_height", lambda: self.fit_to_image("height"))

    def show_context_menu(self, x, y):
        self._install_ctx_actions()
        model = self.context_menu_model()
        if not model.get_n_items():
            return
        if self._ctx_popover is not None:
            self._ctx_popover.unparent()
        pop = Gtk.PopoverMenu.new_from_model(model)
        pop.set_parent(self.area)
        pop.set_has_arrow(False)
        pop.set_halign(Gtk.Align.START)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        pop.connect("closed", lambda p: GLib.idle_add(lambda: (p.unparent(), False)[1]))
        self._ctx_popover = pop
        pop.popup()

    # -- menu operations (each is one undo step)
    @staticmethod
    def _default_size(o):
        """Size 'Reset size' returns an object to, or None: step labels are 30x30, pasted images their own size."""
        if o.kind == "step":
            return M.DEFAULT_SIZE["step"]
        if o.kind == "image" and o.image is not None and not M.is_cursor(o):
            return o.image.shape[1], o.image.shape[0]
        return None

    def reset_size(self):
        targets = [o for o in self.selection if self._default_size(o)]
        if not targets:
            return
        self._push_undo()
        for o in targets:
            w, h = self._default_size(o)
            x, y = o.rect()[:2]
            o.set_rect(x, y, w, h)
        self._changed()

    def _snap_one(self, o, direction):
        iw, ih = self.scene.size
        x, y, w, h = o.rect()
        if o.kind == "freehand" and o.points:
            xs, ys = [p[0] for p in o.points], [p[1] for p in o.points]
            x, y, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        dx = dy = 0.0
        if direction == "left":
            dx = -x
        elif direction == "right":
            dx = iw - (x + w)
        elif direction == "top":
            dy = -y
        elif direction == "bottom":
            dy = ih - (y + h)
        o.translate(dx, dy)

    def snap_to_edge(self, direction):
        """Dock the selection against an edge of the picture."""
        if not self.selection:
            return
        self._push_undo()
        for o in self.selection:
            self._snap_one(o, direction)
        self._changed()

    def fit_to_image(self, which):
        """Stretch the selection to the full width or height of the picture."""
        targets = [o for o in self.selection if o.kind not in ("freehand",)]
        if not targets:
            return
        self._push_undo()
        iw, ih = self.scene.size
        for o in targets:
            x, y, w, h = o.rect()
            if which == "width":
                o.x1, o.x2 = 0, iw
            else:
                o.y1, o.y2 = 0, ih
        self._changed()

    def push_out(self, direction):
        """Make the canvas bigger on one side by the size of the (first) selected object and move it into the new
        space, so a label can sit beside the screenshot instead of on top of it."""
        if not self.selection:
            return
        o = self.selection[0]
        _x, _y, w, h = o.rect()
        left = top = right = bottom = 0
        if direction == "left":
            left = int(math.ceil(w))
        elif direction == "right":
            right = int(math.ceil(w))
        elif direction == "top":
            top = int(math.ceil(h))
        elif direction == "bottom":
            bottom = int(math.ceil(h))
        self._push_undo()
        new_base = im.resize_canvas(self.scene.base, left, top, right, bottom, (0, 0, 0, 0))
        self.scene.replace_base(new_base, lambda px, py: (px + left, py + top))
        self._snap_one(o, direction)
        self.selection = [o]
        self._after_geometry_change()

    # ------------------------------------------------------------------ text editing
    def begin_text_edit(self, o, is_new=False):
        self._finish_text_edit()
        tv = Gtk.TextView()
        tv.add_css_class("snip-text-edit")
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(o.text)
        tv.set_halign(Gtk.Align.START)
        tv.set_valign(Gtk.Align.START)
        tv.set_justification({"left": Gtk.Justification.LEFT, "right": Gtk.Justification.RIGHT}.get(
            o.p.get("halign", "center"), Gtk.Justification.CENTER))
        self._edit = dict(obj=o, view=tv, new=is_new, snap=self.scene.snapshot(), before=o.text)
        self._style_text_edit()
        self.overlay.add_overlay(tv)
        self.scene.touch()
        self.area.queue_draw()
        tv.get_buffer().connect("changed", lambda *_: self._style_text_edit())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._edit_key)
        tv.add_controller(keys)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: GLib.idle_add(self._finish_text_edit))
        tv.add_controller(focus)
        GLib.idle_add(lambda: (tv.grab_focus(), tv.get_buffer().select_range(*tv.get_buffer().get_bounds()))[0] and False)

    def _style_text_edit(self):
        e = self._edit
        if not e:
            return
        o, tv = e["obj"], e["view"]
        buf = tv.get_buffer()
        txt = buf.get_text(*buf.get_bounds(), False)
        probe = copy.copy(o)
        probe.text = txt or " "
        x, y, w, h = o.rect()
        if o.p.get("autosize"):                            # the box hugs the text as you type
            fw, fh = R.fit_text_size(o, txt)
            o.set_rect(x, y, fw, fh)
        else:                                              # fixed width: grow taller when lines wrap
            need = R.text_height(probe)
            if need > h:
                o.set_rect(x, y, w, need)
        x, y, w, h = o.rect()
        tv.set_wrap_mode(Gtk.WrapMode.NONE if o.p.get("autosize") else Gtk.WrapMode.WORD_CHAR)
        wx, wy = self.to_widget(x, y)
        tv.set_margin_start(int(wx))
        tv.set_margin_top(int(wy))
        tv.set_size_request(max(20, int(w * self.zoom) + 2), max(16, int(h * self.zoom) + 2))
        pad = R.text_pad(o) * self.zoom
        th = (R.text_height(probe) - 2 * R.text_pad(o)) * self.zoom
        va = o.p.get("valign", "middle")
        top = pad if va == "top" else (max(pad, int(h * self.zoom - pad - th)) if va == "bottom"
                                       else max(pad, (h * self.zoom - th) / 2))
        tv.set_top_margin(int(top))
        tv.set_left_margin(int(pad))
        tv.set_right_margin(int(pad))
        c = o.p.get("line_color", M.RED)
        fill = o.p.get("fill_color", M.TRANSPARENT)
        css = (".snip-text-edit, .snip-text-edit text { font-family: \"%s\"; font-size: %.1fpx; font-weight: %s; "
               "font-style: %s; color: rgba(%d,%d,%d,%.2f); background: rgba(%d,%d,%d,%.2f); } "
               ".snip-text-edit { border: 1px dashed rgba(30,120,255,.9); }" % (
                   o.p.get("font", "Sans"), o.p.get("font_size", 11) * 96 / 72 * self.zoom,
                   "bold" if o.p.get("bold") else "normal", "italic" if o.p.get("italic") else "normal",
                   c[0] * 255, c[1] * 255, c[2] * 255, c[3], fill[0] * 255, fill[1] * 255, fill[2] * 255,
                   max(fill[3], 0.0) if fill[3] > 0 else 0.0))
        self._text_css.load_from_string(css)

    def _edit_key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            self._finish_text_edit()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (state & Gdk.ModifierType.SHIFT_MASK):
            self._finish_text_edit()
            return True
        return False

    def _finish_text_edit(self):
        e, self._edit = self._edit, None
        if not e:
            return False
        o, tv = e["obj"], e["view"]
        buf = tv.get_buffer()
        text = buf.get_text(*buf.get_bounds(), False)
        self.overlay.remove_overlay(tv)
        o.text = text
        if text.strip() == "" and o.kind == "text":
            self.scene.remove(o)
            self.selection = [s for s in self.selection if s is not o]
            if not e["new"]:
                self._push_undo(e["snap"])
            self.on_selection()
            self.area.queue_draw()
            return True
        x, y, w, h = o.rect()
        if o.p.get("autosize"):
            fw, fh = R.fit_text_size(o)
            o.set_rect(x, y, fw, fh)
        else:
            need = R.text_height(o)
            if need > h:
                o.set_rect(x, y, w, need)
        changed = e["new"] or text != e["before"]
        if changed and not e["new"]:
            self._push_undo(e["snap"])
        self.scene.touch()
        self.area.queue_draw()
        self.on_changed()
        self.area.grab_focus()
        return True

    # ------------------------------------------------------------------ object operations
    def delete_selected(self):
        if not self.selection:
            return
        self._push_undo()
        for o in list(self.selection):
            self.scene.remove(o)
        self.selection = []
        self.on_selection()
        self._changed()

    def copy_selected(self):
        global _object_clipboard
        if self.selection:
            _object_clipboard = [o.clone() for o in self.selection]
            return True
        return False

    def cut_selected(self):
        if self.copy_selected():
            self.delete_selected()

    def paste_objects(self, offset=12):
        if not _object_clipboard:
            return False
        self._push_undo()
        new = []
        for o in _object_clipboard:
            c = o.clone()
            c.uid = next(M._uid)
            c.translate(offset, offset)
            self.scene.add(c)
            new.append(c)
        for o in _object_clipboard:
            o.translate(offset, offset)          # next paste lands a little further along
        self.selection = new
        self.on_selection()
        self._changed()
        return True

    def duplicate_selected(self):
        if not self.selection:
            return
        self._push_undo()
        new = []
        for o in self.selection:
            c = o.clone()
            c.uid = next(M._uid)
            c.translate(12, 12)
            self.scene.add(c)
            new.append(c)
        self.selection = new
        self.on_selection()
        self._changed()

    def nudge(self, dx, dy):
        if not self.selection:
            return
        self._push_undo()
        for o in self.selection:
            o.translate(dx, dy)
        self._changed()

    def arrange(self, how):
        if not self.selection:
            return
        self._push_undo()
        fn = {"front": self.scene.raise_to_top, "back": self.scene.lower_to_bottom,
              "up": self.scene.raise_one, "down": self.scene.lower_one}[how]
        for o in (self.selection if how in ("front", "up") else reversed(self.selection)):
            fn(o)
        self._changed()

    def add_cursor(self, shape="arrow", sprite=None, at=None):
        """Insert a mouse cursor as a movable, resizable object (like Greenshot's cursor container).
        ``sprite`` is (array, x, y) for a cursor captured with the screenshot; otherwise the theme's cursor
        for ``shape`` is placed with its hotspot at the pointer (or the middle of the picture)."""
        import cursors
        self._push_undo()
        iw, ih = self.scene.size
        if sprite is not None:
            arr, x, y = sprite
        else:
            arr, hx, hy = cursors.get(shape)
            px, py = at or (self._pointer if 0 <= self._pointer[0] < iw and 0 <= self._pointer[1] < ih
                            else (iw / 2, ih / 2))
            x, y = px - hx, py - hy
        h, w = arr.shape[:2]
        o = M.Obj("image", x, y, x + w, y + h)
        o.image = arr
        o.p["cursor"] = True
        self.scene.add(o)
        self.selection = [o]
        self.on_selection()
        self._changed()
        return o

    def add_image_object(self, arr):
        """Paste an image from the clipboard as a movable, resizable object."""
        self._push_undo()
        h, w = arr.shape[:2]
        iw, ih = self.scene.size
        sc = min(1.0, iw * 0.6 / w, ih * 0.6 / h)
        o = M.Obj("image", 20, 20, 20 + w * sc, 20 + h * sc)
        o.image = arr
        self.scene.add(o)
        self.selection = [o]
        self.on_selection()
        self._changed()

    # ------------------------------------------------------------------ crop / whole-image operations
    def crop_confirm(self):
        c = self.crop
        if c is None:
            return False
        x, y, w, h = [int(round(v)) for v in c.rect()]
        iw, ih = self.scene.size
        mode = c.p.get("mode", "default")
        if w < 1 or h < 1:
            return False
        self._push_undo()
        if mode == "vertical":                               # cut a vertical strip out and join the rest
            import numpy as np
            base = self.scene.base
            keep = np.concatenate([base[:, :x], base[:, x + w:]], axis=1) if x + w < iw else base[:, :x]
            if keep.shape[1] < 1:
                self.undo_stack.pop()
                return False
            self.scene.replace_base(np.ascontiguousarray(keep),
                                    lambda px, py: (px if px < x else max(x, px - w), py))
        elif mode == "horizontal":
            import numpy as np
            base = self.scene.base
            keep = np.concatenate([base[:y], base[y + h:]], axis=0) if y + h < ih else base[:y]
            if keep.shape[0] < 1:
                self.undo_stack.pop()
                return False
            self.scene.replace_base(np.ascontiguousarray(keep),
                                    lambda px, py: (px, py if py < y else max(y, py - h)))
        else:
            self.scene.crop_to(x, y, w, h)
        self.crop = None
        self.selection = []
        self._after_geometry_change()
        return True

    def crop_cancel(self):
        self.crop = None
        self.on_selection()
        self.area.queue_draw()

    def crop_auto(self):
        x, y, w, h = im.auto_crop_box(self.scene.base)
        self.crop = M.new_obj("crop", x, y, mode="default")
        self.crop.set_rect(x, y, w, h)
        self.set_tool_silent("crop")
        self.on_selection()
        self.area.queue_draw()

    def set_tool_silent(self, tool):
        self.tool = tool
        self.area.set_cursor_from_name("crosshair")

    def apply_base_effect(self, fn, label_changes_size=True):
        """Run an image effect (array -> array) on the base image; annotations stay attached to the image."""
        self._finish_text_edit()
        self._push_undo()
        old = self.scene.size
        self.scene.replace_base(fn(self.scene.base))
        self._after_geometry_change(old)

    def apply_with_offset(self, new_base, dx, dy):
        """Effects that grow the canvas (border, shadow, canvas resize): annotations move with the picture."""
        self._finish_text_edit()
        self._push_undo()
        self.scene.replace_base(new_base, lambda px, py: (px + dx, py + dy))
        self._after_geometry_change()

    def rotate(self, clockwise):
        self._finish_text_edit()
        self._push_undo()
        self.scene.rotate(clockwise)
        self._after_geometry_change()

    def scale_to(self, w, h):
        self._finish_text_edit()
        self._push_undo()
        self.scene.scale(w, h, im.resize(self.scene.base, w, h))
        self._after_geometry_change()

    def _after_geometry_change(self, old=None):
        self._update_size()
        self._maybe_refit()
        self.on_size()
        self.on_changed()
        self.on_selection()
        self.area.queue_draw()
