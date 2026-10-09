"""Scene model for Snipshot: the base image plus a stack of annotation objects.

Plain data and geometry only (no drawing, no GUI), so it can be unit-tested.
Defaults follow Greenshot's: red 2px outlines with a shadow, blue speech bubbles, dark-red step labels, etc.
"""
import copy
import itertools
import math

import numpy as np

# colours are (r, g, b, a) floats 0..1
RED = (1.0, 0.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0, 1.0)
YELLOW = (1.0, 1.0, 0.0, 1.0)
DARK_RED = (0.545, 0.0, 0.0, 1.0)
DIM_GRAY = (0.412, 0.412, 0.412, 1.0)
TRANSPARENT = (0.0, 0.0, 0.0, 0.0)

RECT_LIKE = ("rect", "ellipse", "text", "speech", "step", "obfuscate", "highlight", "crop", "image")
LINE_LIKE = ("line", "arrow")
FILTER_KINDS = ("obfuscate", "highlight")            # these transform the pixels beneath them

# arrowhead placement, as in Greenshot
ARROW_NONE, ARROW_START, ARROW_END, ARROW_BOTH = "none", "start", "end", "both"

DEFAULTS = {
    "rect": dict(line_color=RED, fill_color=TRANSPARENT, thickness=2, shadow=True),
    "ellipse": dict(line_color=RED, fill_color=TRANSPARENT, thickness=2, shadow=True),
    "line": dict(line_color=RED, thickness=2, shadow=True),
    "arrow": dict(line_color=RED, thickness=2, shadow=True, arrowheads=ARROW_END),
    "freehand": dict(line_color=RED, thickness=3, shadow=False),
    "text": dict(line_color=RED, fill_color=TRANSPARENT, thickness=2, shadow=True, font="Sans", font_size=11.0,
                 bold=False, italic=False, halign="center", valign="middle", autosize=False),
    "speech": dict(line_color=BLUE, fill_color=WHITE, thickness=2, shadow=False, font="Sans", font_size=20.0,
                   bold=True, italic=False, halign="center", valign="middle"),
    "step": dict(line_color=WHITE, fill_color=DARK_RED, thickness=0, shadow=False),
    # pixel_size = size of each mosaic block; blur_radius = box-blur radius (applied twice each way)
    "obfuscate": dict(preset="pixelize", pixel_size=10, blur_radius=10, randomise=False),
    # preset: text (yellow marker) | area (dim outside) | gray (grey outside) | magnify
    "highlight": dict(preset="text", fill_color=YELLOW, brightness=0.5, magnification=2),
    "crop": dict(mode="default"),
    "image": dict(shadow=False, cursor=False),
}

DEFAULT_SIZE = {"step": (30, 30)}

_uid = itertools.count(1)


class Obj:
    """One annotation. Geometry is a start point (x1, y1) and an end point (x2, y2) in image pixels."""

    def __init__(self, kind, x1=0.0, y1=0.0, x2=0.0, y2=0.0, **props):
        self.uid = next(_uid)
        self.kind = kind
        self.x1, self.y1, self.x2, self.y2 = float(x1), float(y1), float(x2), float(y2)
        self.p = copy.deepcopy(DEFAULTS[kind])
        self.p.update(props)
        self.points = []          # freehand: [(x, y), ...]
        self.text = ""
        self.tail = None          # speech bubble: (x, y) the tail points at
        self.image = None         # image objects: BGRA array

    # -- geometry
    def rect(self):
        x, y = min(self.x1, self.x2), min(self.y1, self.y2)
        return x, y, abs(self.x2 - self.x1), abs(self.y2 - self.y1)

    def set_rect(self, x, y, w, h):
        self.x1, self.y1, self.x2, self.y2 = x, y, x + w, y + h

    def translate(self, dx, dy):
        self.x1 += dx
        self.x2 += dx
        self.y1 += dy
        self.y2 += dy
        self.points = [(px + dx, py + dy) for px, py in self.points]
        if self.tail:
            self.tail = (self.tail[0] + dx, self.tail[1] + dy)

    def map_points(self, fn):
        """Apply fn(x, y) -> (x, y) to every point (used by rotate / resize canvas / scale)."""
        self.x1, self.y1 = fn(self.x1, self.y1)
        self.x2, self.y2 = fn(self.x2, self.y2)
        self.points = [fn(px, py) for px, py in self.points]
        if self.tail:
            self.tail = fn(*self.tail)

    def clone(self):
        c = copy.copy(self)
        c.p = copy.deepcopy(self.p)
        c.points = list(self.points)
        return c                      # uid is kept on purpose: undo restores the same object

    @property
    def shadow(self):
        return bool(self.p.get("shadow"))

    def is_empty(self, min_size=2):
        if self.kind == "freehand":
            return len(self.points) < 2
        _, _, w, h = self.rect()
        if self.kind in LINE_LIKE:
            return math.hypot(w, h) < min_size
        return w < min_size and h < min_size


def new_obj(kind, x, y, **props):
    o = Obj(kind, x, y, x, y, **props)
    if kind == "freehand":
        o.points = [(x, y)]
    return o


# --------------------------------------------------------------------------- hit testing

def dist_point_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _ellipse_value(px, py, x, y, w, h):
    """<1 inside the ellipse, 1 on it, >1 outside (normalised)."""
    if w <= 0 or h <= 0:
        return 99.0
    cx, cy = x + w / 2, y + h / 2
    return ((px - cx) / (w / 2)) ** 2 + ((py - cy) / (h / 2)) ** 2


def hit(obj, px, py, tol=4.0):
    """Is the point on this object? Outline-only shapes are only hit on their outline, like Greenshot."""
    k = obj.kind
    x, y, w, h = obj.rect()
    if k in LINE_LIKE:
        return dist_point_segment(px, py, obj.x1, obj.y1, obj.x2, obj.y2) <= obj.p.get("thickness", 2) / 2 + tol
    if k == "freehand":
        t = obj.p.get("thickness", 3) / 2 + tol
        pts = obj.points
        if len(pts) == 1:
            return math.hypot(px - pts[0][0], py - pts[0][1]) <= t
        return any(dist_point_segment(px, py, *pts[i], *pts[i + 1]) <= t for i in range(len(pts) - 1))
    filled = obj.p.get("fill_color", (0, 0, 0, 1))[3] > 0 or k not in ("rect", "ellipse")
    if k == "ellipse":
        v = _ellipse_value(px, py, x, y, w, h)
        if filled:
            return v <= 1.0 + (tol * 2) / max(1.0, min(w, h) / 2)
        edge = (tol + obj.p.get("thickness", 2)) / max(1.0, min(w, h) / 2)
        return abs(math.sqrt(v) - 1.0) <= edge
    if k == "step":
        return _ellipse_value(px, py, x, y, w, h) <= 1.0
    if k == "speech" and obj.tail:
        if dist_point_segment(px, py, x + w / 2, y + h / 2, *obj.tail) <= tol + 6:
            return True
    inside = x - tol <= px <= x + w + tol and y - tol <= py <= y + h + tol
    if not inside:
        return False
    if filled:
        return True
    t = obj.p.get("thickness", 2) + tol            # outline-only rectangle: near any edge
    return px < x + t or px > x + w - t or py < y + t or py > y + h - t


# --------------------------------------------------------------------------- handles

HANDLE_ORDER = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
HANDLE_CURSOR = {"nw": "nwse-resize", "se": "nwse-resize", "ne": "nesw-resize", "sw": "nesw-resize",
                 "n": "ns-resize", "s": "ns-resize", "e": "ew-resize", "w": "ew-resize",
                 "start": "move", "end": "move", "tail": "move"}


def is_cursor(obj):
    """A mouse-cursor image: it can be moved and re-ordered but not resized."""
    return obj.kind == "image" and bool(obj.p.get("cursor"))


def handles(obj):
    """[(name, x, y)] of the grab handles an object shows when selected."""
    if obj.kind in LINE_LIKE:
        return [("start", obj.x1, obj.y1), ("end", obj.x2, obj.y2)]
    if obj.kind == "freehand" or is_cursor(obj):
        return []
    x, y, w, h = obj.rect()
    pos = {"nw": (x, y), "n": (x + w / 2, y), "ne": (x + w, y), "e": (x + w, y + h / 2),
           "se": (x + w, y + h), "s": (x + w / 2, y + h), "sw": (x, y + h), "w": (x, y + h / 2)}
    out = [(n, *pos[n]) for n in HANDLE_ORDER]
    if obj.kind == "speech" and obj.tail:
        out.append(("tail", *obj.tail))
    return out


def handle_at(obj, px, py, radius):
    for name, hx, hy in reversed(handles(obj)):
        if abs(px - hx) <= radius and abs(py - hy) <= radius:
            return name
    return None


def drag_handle(obj, name, px, py, keep_square=False):
    """Move a handle to (px, py), updating the object's geometry."""
    if name == "start":
        obj.x1, obj.y1 = px, py
        return
    if name == "end":
        obj.x2, obj.y2 = px, py
        return
    if name == "tail":
        obj.tail = (px, py)
        return
    x, y, w, h = obj.rect()
    left, top, right, bottom = x, y, x + w, y + h
    if "w" in name:
        left = px
    if "e" in name:
        right = px
    if "n" in name:
        top = py
    if "s" in name:
        bottom = py
    if keep_square or obj.kind == "step":
        side = max(abs(right - left), abs(bottom - top))
        sx = 1 if right >= left else -1
        sy = 1 if bottom >= top else -1
        if "w" in name:
            left = right - sx * side
        else:
            right = left + sx * side
        if "n" in name:
            top = bottom - sy * side
        else:
            bottom = top + sy * side
    obj.x1, obj.y1, obj.x2, obj.y2 = left, top, right, bottom


def constrain_end(kind, x1, y1, x2, y2):
    """Shift held while drawing: lines snap to 45 degree steps, boxes to squares/circles."""
    dx, dy = x2 - x1, y2 - y1
    if kind in LINE_LIKE:
        ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        d = math.hypot(dx, dy)
        return x1 + d * math.cos(ang), y1 + d * math.sin(ang)
    side = max(abs(dx), abs(dy))
    return x1 + math.copysign(side, dx or 1), y1 + math.copysign(side, dy or 1)


# --------------------------------------------------------------------------- scene

class Scene:
    def __init__(self, base):
        self.base = base                  # BGRA premultiplied array
        self.objects = []
        self.counter_start = 1
        self.version = 0                  # bumped on any change, lets views cache the render

    @property
    def size(self):
        return self.base.shape[1], self.base.shape[0]

    def touch(self):
        self.version += 1

    # -- editing
    def add(self, obj, index=None):
        if index is None:
            self.objects.append(obj)
        else:
            self.objects.insert(index, obj)
        self.touch()
        return obj

    def remove(self, obj):
        if obj in self.objects:
            self.objects.remove(obj)
            self.touch()

    def step_number(self, obj):
        """Step labels count 1, 2, 3 ... in drawing order, from ``counter_start`` (renumbers on delete)."""
        n = self.counter_start
        for o in self.objects:
            if o.kind == "step":
                if o is obj:
                    return n
                n += 1
        return n

    def top_hit(self, px, py, tol=4.0, kinds_skip=("crop",)):
        for obj in reversed(self.objects):
            if obj.kind not in kinds_skip and hit(obj, px, py, tol):
                return obj
        return None

    def raise_to_top(self, obj):
        self._move(obj, len(self.objects) - 1)

    def lower_to_bottom(self, obj):
        self._move(obj, 0)

    def raise_one(self, obj):
        self._move(obj, min(len(self.objects) - 1, self.objects.index(obj) + 1))

    def lower_one(self, obj):
        self._move(obj, max(0, self.objects.index(obj) - 1))

    def _move(self, obj, idx):
        if obj in self.objects:
            self.objects.remove(obj)
            self.objects.insert(idx, obj)
            self.touch()

    # -- undo support
    def snapshot(self):
        return dict(base=self.base, objects=[o.clone() for o in self.objects], counter_start=self.counter_start)

    def restore(self, snap):
        self.base = snap["base"]
        self.objects = [o.clone() for o in snap["objects"]]
        self.counter_start = snap["counter_start"]
        self.touch()

    # -- whole-image changes keep annotations attached to the same pixels
    def replace_base(self, new_base, point_map=None):
        self.base = new_base
        if point_map:
            for o in self.objects:
                o.map_points(point_map)
        self.touch()

    def crop_to(self, x, y, w, h):
        x, y = int(x), int(y)
        w, h = int(w), int(h)
        self.replace_base(np.ascontiguousarray(self.base[y:y + h, x:x + w]), lambda px, py: (px - x, py - y))

    def rotate(self, clockwise=True):
        from imaging import rotate90
        h, w = self.base.shape[:2]
        if clockwise:
            fn = lambda px, py: (h - py, px)
        else:
            fn = lambda px, py: (py, w - px)
        self.replace_base(rotate90(self.base, clockwise), fn)

    def scale(self, new_w, new_h, resized_base):
        """Image resized: annotations stay on the same content (positions scale, line widths do not)."""
        w, h = self.size
        sx, sy = new_w / w, new_h / h
        self.replace_base(resized_base, lambda px, py: (px * sx, py * sy))
