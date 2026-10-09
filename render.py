"""Draws a Scene (base image + annotation objects) with cairo, Pango and the effects engine.

No GTK: this renders to a cairo ImageSurface, which the editor shows on screen and which is also what gets
saved, copied and printed, so exports always match what you see.
"""
import math

import cairo
import gi
import numpy as np
from PIL import Image

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

import effects as fx  # noqa: E402
import imaging as im  # noqa: E402
from model import (ARROW_BOTH, ARROW_END, ARROW_START, LINE_LIKE)  # noqa: E402

SHADOW_OFFSET = 3
SHADOW_ALPHA = 0.45
SHADOW_BLUR = 2


# --------------------------------------------------------------------------- helpers

def write_region(surf, x, y, arr):
    """Copy a BGRA array into an ImageSurface at (x, y), clipped to the surface."""
    surf.flush()
    sw, sh = surf.get_width(), surf.get_height()
    h, w = arr.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(sw, x + w), min(sh, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    view = np.ndarray((sh, surf.get_stride()), dtype=np.uint8, buffer=surf.get_data())[:, : sw * 4].reshape(sh, sw, 4)
    view[y0:y1, x0:x1] = arr[y0 - y:y1 - y, x0 - x:x1 - x]
    surf.mark_dirty()


def _col(cr, c, alpha=1.0):
    cr.set_source_rgba(c[0], c[1], c[2], c[3] * alpha)


def int_rect(o, w, h):
    """The object's rectangle as ints, clipped to a w x h image (None if nothing is left)."""
    x, y, rw, rh = o.rect()
    x0, y0 = max(0, int(math.floor(x))), max(0, int(math.floor(y)))
    x1, y1 = min(w, int(math.ceil(x + rw))), min(h, int(math.ceil(y + rh)))
    return (x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None


# --------------------------------------------------------------------------- text

def make_layout(cr, o, width_px, text=None, size=None):
    layout = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription()
    fd.set_family(o.p.get("font", "Sans"))
    fd.set_absolute_size(int((size if size is not None else o.p.get("font_size", 11) * 96 / 72) * Pango.SCALE))
    fd.set_weight(Pango.Weight.BOLD if o.p.get("bold") else Pango.Weight.NORMAL)
    fd.set_style(Pango.Style.ITALIC if o.p.get("italic") else Pango.Style.NORMAL)
    layout.set_font_description(fd)
    if width_px is not None:
        layout.set_width(int(max(1, width_px) * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
    layout.set_alignment({"left": Pango.Alignment.LEFT, "right": Pango.Alignment.RIGHT}.get(
        o.p.get("halign", "center"), Pango.Alignment.CENTER))
    layout.set_text(o.text if text is None else text, -1)
    return layout


_scratch = None


def _scratch_cr():
    global _scratch
    if _scratch is None:
        _scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
    return _scratch


def text_pad(o):
    """Space between the text and the box edge. Kept small so a single character sits in a tidy square."""
    return max(2, o.p.get("thickness", 0) + 2)


def text_height(o, width=None):
    """Height in px the text needs inside the object's width (used to grow text boxes)."""
    w = o.rect()[2] if width is None else width
    pad = text_pad(o)
    layout = make_layout(_scratch_cr(), o, max(1, w - 2 * pad))
    return layout.get_pixel_size()[1] + 2 * pad


def fit_text_size(o, text=None):
    """(width, height) of a box that just fits the text on its own lines: the shrink-wrap size Greenshot users
    expect while typing. At least as wide as one line is tall, so a single character gets a square."""
    pad = text_pad(o)
    layout = make_layout(_scratch_cr(), o, None, text=(o.text if text is None else text) or " ")
    tw, th = layout.get_pixel_size()
    line_h = make_layout(_scratch_cr(), o, None, text=" ").get_pixel_size()[1]
    return max(tw + 2 * pad, line_h + 2 * pad), th + 2 * pad       # one short line -> a square; more text -> wider


def _draw_text(cr, o):
    x, y, w, h = o.rect()
    pad = text_pad(o)
    layout = make_layout(cr, o, max(1, w - 2 * pad))
    tw, th = layout.get_pixel_size()
    va = o.p.get("valign", "middle")
    ty = y + pad if va == "top" else (y + h - pad - th if va == "bottom" else y + (h - th) / 2)
    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    cr.move_to(x + pad, ty)
    _col(cr, o.p.get("line_color"))
    PangoCairo.show_layout(cr, layout)
    cr.restore()


# --------------------------------------------------------------------------- shapes

def _rounded_rect_points(x, y, w, h, r, steps=10):
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for i in range(steps + 1):
            a = math.radians(a0 + 90 * i / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _seg_intersect(p, q, a, b):
    """Intersection of segments pq and ab, or None."""
    rx, ry, sx, sy = q[0] - p[0], q[1] - p[1], b[0] - a[0], b[1] - a[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-9:
        return None
    t = ((a[0] - p[0]) * sy - (a[1] - p[1]) * sx) / den
    u = ((a[0] - p[0]) * ry - (a[1] - p[1]) * rx) / den
    return (p[0] + t * rx, p[1] + t * ry, u) if 0 <= t <= 1 and 0 <= u <= 1 else None


def speech_outline(o):
    """Polygon of a rounded rectangle with its tail merged in, as Greenshot draws speech bubbles.

    The tail is a triangle from the bubble's centre to the target point. Where its two edges leave the
    rounded rectangle, the short stretch of border between them is replaced by the edges out to the tip."""
    x, y, w, h = o.rect()
    t = o.p.get("thickness", 2)
    r = max(0, min(30, min(w, h) / 2 - t))
    ring = _rounded_rect_points(x, y, w, h, r) if r > 0 else [(x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    if not o.tail:
        return ring
    cx, cy = x + w / 2, y + h / 2
    tx, ty = o.tail
    length = math.hypot(tx - cx, ty - cy)
    if length < 1e-6:
        return ring
    tw = min(w / 2, h / 2, (abs(w) + abs(h)) / 20)
    ux, uy = (tx - cx) / length, (ty - cy) / length
    nx, ny = -uy, ux
    n = len(ring)
    exits = []                                   # (position along the ring, point) for each tail edge
    for base in ((cx + nx * tw, cy + ny * tw), (cx - nx * tw, cy - ny * tw)):
        found = None
        for i in range(n):
            res = _seg_intersect(base, (tx, ty), ring[i], ring[(i + 1) % n])
            if res:
                found = (i + res[2], (res[0], res[1]))
                break
        if found is None:
            return ring                          # target is inside the bubble: no visible tail
        exits.append(found)
    (s1, p1), (s2, p2) = exits
    # the stretch of border covered by the tail is the SHORT arc between the two exits
    if (s2 - s1) % n <= n / 2:
        (sa, pa), (sb, pb) = (s1, p1), (s2, p2)
    else:
        (sa, pa), (sb, pb) = (s2, p2), (s1, p1)
    out = [pb]
    j = int(math.floor(sb)) + 1
    last = int(math.floor(sa)) % n
    for _ in range(n + 1):
        out.append(ring[j % n])
        if j % n == last:
            break
        j += 1
    out += [pa, (tx, ty)]
    return out


def _path_poly(cr, pts):
    cr.new_path()
    cr.move_to(*pts[0])
    for p in pts[1:]:
        cr.line_to(*p)
    cr.close_path()


def _ellipse_path(cr, x, y, w, h):
    cr.save()
    cr.translate(x + w / 2, y + h / 2)
    cr.scale(max(w, 1e-6) / 2, max(h, 1e-6) / 2)
    cr.new_path()
    cr.arc(0, 0, 1, 0, 2 * math.pi)
    cr.restore()


def _fill_stroke(cr, o, path_fn, inset):
    """Fill with fill_color, outline with line_color, outline kept inside the object's bounds."""
    t = o.p.get("thickness", 0)
    x, y, w, h = o.rect()
    d = t / 2 if inset else 0
    x, y, w, h = x + d, y + d, max(0.0, w - 2 * d), max(0.0, h - 2 * d)
    fill = o.p.get("fill_color")
    if fill and fill[3] > 0:
        path_fn(cr, x, y, w, h)
        _col(cr, fill)
        cr.fill()
    if t > 0:
        path_fn(cr, x, y, w, h)
        _col(cr, o.p.get("line_color"))
        cr.set_line_width(t)
        cr.set_line_join(cairo.LINE_JOIN_MITER)
        cr.stroke()


def _rect_path(cr, x, y, w, h):
    cr.new_path()
    cr.rectangle(x, y, w, h)


def arrow_geometry(o):
    """Arrowhead polygons and the shortened line, matching Greenshot's cap: 4x6 times the line width."""
    t = max(1.0, o.p.get("thickness", 2))
    head_w, head_l = 4 * t, 6 * t
    heads = o.p.get("arrowheads", ARROW_END)
    ax, ay, bx, by = o.x1, o.y1, o.x2, o.y2
    d = math.hypot(bx - ax, by - ay)
    if d < 1e-6:
        return (ax, ay, bx, by), []
    ux, uy = (bx - ax) / d, (by - ay) / d
    nx, ny = -uy, ux
    polys = []
    sa, sb = (ax, ay), (bx, by)
    shrink = min(head_l, d / 2)
    if heads in (ARROW_END, ARROW_BOTH):
        base = (bx - ux * shrink, by - uy * shrink)
        polys.append([(bx, by), (base[0] + nx * head_w / 2, base[1] + ny * head_w / 2),
                      (base[0] - nx * head_w / 2, base[1] - ny * head_w / 2)])
        sb = base
    if heads in (ARROW_START, ARROW_BOTH):
        base = (ax + ux * shrink, ay + uy * shrink)
        polys.append([(ax, ay), (base[0] + nx * head_w / 2, base[1] + ny * head_w / 2),
                      (base[0] - nx * head_w / 2, base[1] - ny * head_w / 2)])
        sa = base
    return (sa[0], sa[1], sb[0], sb[1]), polys


def _draw_step(cr, o, number):
    x, y, w, h = o.rect()
    _ellipse_path(cr, x, y, w, h)
    _col(cr, o.p.get("fill_color"))
    cr.fill()
    t = o.p.get("thickness", 0)
    if t > 0:
        _ellipse_path(cr, x + t / 2, y + t / 2, w - t, h - t)
        _col(cr, o.p.get("line_color"))
        cr.set_line_width(t)
        cr.stroke()
    text = str(number)
    side = min(w, h)
    layout = make_layout(cr, o, None, text=text, size=side * 0.62)
    fd = layout.get_font_description()
    fd.set_weight(Pango.Weight.BOLD)
    layout.set_font_description(fd)
    tw, th = layout.get_pixel_size()
    if tw > side * 0.72 and tw > 0:                       # long numbers shrink to fit
        fd.set_absolute_size(int(side * 0.62 * (side * 0.72) / tw * Pango.SCALE))
        layout.set_font_description(fd)
        tw, th = layout.get_pixel_size()
    _col(cr, o.p.get("line_color"))
    cr.move_to(x + (w - tw) / 2, y + (h - th) / 2)
    PangoCairo.show_layout(cr, layout)


# --------------------------------------------------------------------------- one object

def draw_body(cr, o, scene=None):
    k = o.kind
    if k == "rect":
        _fill_stroke(cr, o, _rect_path, True)
    elif k == "ellipse":
        _fill_stroke(cr, o, _ellipse_path, True)
    elif k == "line":
        t = o.p.get("thickness", 2)
        if t > 0:
            cr.new_path()
            cr.move_to(o.x1, o.y1)
            cr.line_to(o.x2, o.y2)
            _col(cr, o.p.get("line_color"))
            cr.set_line_width(t)
            cr.set_line_cap(cairo.LINE_CAP_BUTT)
            cr.stroke()
    elif k == "arrow":
        t = o.p.get("thickness", 2)
        if t > 0:
            (ax, ay, bx, by), polys = arrow_geometry(o)
            _col(cr, o.p.get("line_color"))
            cr.new_path()
            cr.move_to(ax, ay)
            cr.line_to(bx, by)
            cr.set_line_width(t)
            cr.set_line_cap(cairo.LINE_CAP_BUTT)
            cr.stroke()
            for poly in polys:
                _path_poly(cr, poly)
                cr.fill()
    elif k == "freehand":
        pts = o.points
        if len(pts) >= 1:
            _col(cr, o.p.get("line_color"))
            cr.set_line_width(o.p.get("thickness", 3))
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.new_path()
            cr.move_to(*pts[0])
            if len(pts) == 1:
                cr.line_to(pts[0][0] + 0.01, pts[0][1])
            for p in pts[1:]:
                cr.line_to(*p)
            cr.stroke()
    elif k == "text":
        _fill_stroke(cr, o, _rect_path, True)
        _draw_text(cr, o)
    elif k == "speech":
        poly = speech_outline(o)
        t = o.p.get("thickness", 2)
        _path_poly(cr, poly)
        _col(cr, o.p.get("fill_color"))
        cr.fill_preserve() if t <= 0 else cr.fill()
        if t > 0:
            _path_poly(cr, poly)
            _col(cr, o.p.get("line_color"))
            cr.set_line_width(t)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.stroke()
        _draw_text(cr, o) if o.text else None
    elif k == "step":
        _draw_step(cr, o, scene.step_number(o) if scene else 1)
    elif k == "image" and o.image is not None:
        x, y, w, h = o.rect()
        surf = im.to_surface(o.image)
        cr.save()
        cr.translate(x, y)
        cr.scale(w / surf.get_width(), h / surf.get_height()) if surf.get_width() and surf.get_height() else None
        cr.set_source_surface(surf, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_BEST)
        cr.paint()
        cr.restore()


def object_pad(o):
    """Extra pixels around an object's rectangle that its drawing may touch (strokes, heads, tail)."""
    t = o.p.get("thickness", 0)
    return 8 * max(1, t) + 4


def object_bbox(o):
    """(x0, y0, x1, y1) floats that contain everything the object draws."""
    if o.kind == "freehand" and o.points:
        xs, ys = [p[0] for p in o.points], [p[1] for p in o.points]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    else:
        x, y, w, h = o.rect()
        x0, y0, x1, y1 = x, y, x + w, y + h
    if o.kind == "speech" and o.tail:
        x0, y0, x1, y1 = min(x0, o.tail[0]), min(y0, o.tail[1]), max(x1, o.tail[0]), max(y1, o.tail[1])
    pad = object_pad(o)
    return x0 - pad, y0 - pad, x1 + pad, y1 + pad


def draw_shadow(cr, o, scene=None):
    """Soft drop shadow: draw the object offscreen, blur its alpha, tint it dark, paint offset."""
    bx0, by0, bx1, by1 = object_bbox(o)
    x0, y0 = int(math.floor(bx0)), int(math.floor(by0))
    w, h = int(math.ceil(bx1)) - x0 + 1, int(math.ceil(by1)) - y0 + 1
    if w <= 0 or h <= 0 or w * h > 40_000_000:
        return
    tmp = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    tcr = cairo.Context(tmp)
    tcr.translate(-x0, -y0)
    draw_body(tcr, o, scene)
    arr = im.from_surface(tmp)
    alpha = np.zeros_like(arr)
    alpha[..., 3] = arr[..., 3]
    soft = fx.blur(alpha, SHADOW_BLUR)
    sh = np.zeros_like(soft)
    sh[..., 3] = np.clip(soft[..., 3].astype(np.float32) * SHADOW_ALPHA, 0, 255).astype(np.uint8)
    cr.set_source_surface(im.to_surface(sh), x0 + SHADOW_OFFSET, y0 + SHADOW_OFFSET)
    cr.paint()


# --------------------------------------------------------------------------- filters (obfuscate / highlight)

def apply_filter(acc, o):
    """Transform the pixels already drawn in ``acc`` under a filter object (obfuscate or highlight)."""
    w, h = acc.get_width(), acc.get_height()
    r = int_rect(o, w, h)
    if r is None:
        return
    x, y, rw, rh = r
    if o.kind == "obfuscate":
        if o.p.get("preset") == "blur":
            rad = int(o.p.get("blur_radius", 10))
            m = fx.blur_margin(rad)
            px0, py0 = max(0, x - m), max(0, y - m)
            px1, py1 = min(w, x + rw + m), min(h, y + rh + m)
            padded = fx.blur(im.from_surface(acc, px0, py0, px1 - px0, py1 - py0), rad)
            out = padded[y - py0:y - py0 + rh, x - px0:x - px0 + rw]
        else:
            region = im.from_surface(acc, x, y, rw, rh)
            out = fx.pixelate(region, int(o.p.get("pixel_size", 10)), bool(o.p.get("randomise")), seed=o.uid)
        write_region(acc, x, y, out)
        return
    preset = o.p.get("preset", "text")
    if preset == "text":
        cr = cairo.Context(acc)
        cr.set_operator(cairo.OPERATOR_MULTIPLY)
        _col(cr, o.p.get("fill_color"))
        cr.rectangle(x, y, rw, rh)
        cr.fill()
    elif preset in ("area", "gray"):
        full = im.from_surface(acc)
        if preset == "area":
            b = float(o.p.get("brightness", 0.5))
            out = full.copy()
            out[..., :3] = np.clip(full[..., :3].astype(np.float32) * b, 0, 255).astype(np.uint8)
        else:
            out = im.grayscale(full)
        out[y:y + rh, x:x + rw] = full[y:y + rh, x:x + rw]
        write_region(acc, 0, 0, out)
    elif preset == "magnify":
        f = max(1.0, float(o.p.get("magnification", 2)))
        cw, ch = rw / f, rh / f
        cx, cy = x + rw / 2, y + rh / 2
        sx0, sy0 = int(max(0, cx - cw / 2)), int(max(0, cy - ch / 2))
        sx1, sy1 = int(min(w, cx + cw / 2)), int(min(h, cy + ch / 2))
        if sx1 > sx0 and sy1 > sy0:
            src = im.from_surface(acc, sx0, sy0, sx1 - sx0, sy1 - sy0)
            write_region(acc, x, y, im.resize(src, rw, rh))
        cr = cairo.Context(acc)
        cr.rectangle(x + 0.5, y + 0.5, rw - 1, rh - 1)
        cr.set_source_rgba(0.25, 0.25, 0.25, 1)
        cr.set_line_width(1)
        cr.stroke()


# --------------------------------------------------------------------------- whole scene

def draw_object(cr, acc, o, scene):
    if o.kind == "crop":
        return
    if o.kind in ("obfuscate", "highlight"):
        apply_filter(acc, o)
        return
    if o.shadow and o.kind not in ("freehand",):
        draw_shadow(cr, o, scene)
    draw_body(cr, o, scene)


def render_scene(scene, hide=()):
    """The finished image (what gets saved / copied): base plus all objects. ``hide`` skips objects by uid."""
    acc = im.to_surface(scene.base)
    cr = cairo.Context(acc)
    for o in scene.objects:
        if o.uid in hide:
            continue
        draw_object(cr, acc, o, scene)
        acc.flush()
    return acc
