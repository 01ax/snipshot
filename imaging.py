"""Image plumbing and whole-image effects for Snipshot.

Pixels are kept as ``H x W x 4`` uint8 arrays in cairo's native layout: B, G, R, A, premultiplied alpha.
Screenshots are opaque, so premultiplication only matters after effects that add transparency
(rotate, torn edge, drop shadow, resize canvas), and cairo then composites them correctly.

No GUI imports; only NumPy, Pillow and cairo.
"""
import io

import cairo
import numpy as np
from PIL import Image, ImageFilter

import effects as fx


# --------------------------------------------------------------------------- conversion

def from_pil(img):
    """PIL image (any mode) -> premultiplied BGRA array."""
    rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    a = rgba[..., 3:4].astype(np.uint16)
    rgb = ((rgba[..., :3].astype(np.uint16) * a + 127) // 255).astype(np.uint8)
    out = np.empty(rgba.shape, dtype=np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = rgb[..., 2], rgb[..., 1], rgb[..., 0]
    out[..., 3] = rgba[..., 3]
    return out


def to_pil(arr):
    """Premultiplied BGRA array -> straight-alpha RGBA PIL image."""
    a = arr[..., 3:4].astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        rgb = np.where(a > 0, arr[..., :3].astype(np.float32) * 255.0 / np.maximum(a, 1), 0)
    rgb = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    out = np.empty(arr.shape, dtype=np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = rgb[..., 2], rgb[..., 1], rgb[..., 0]
    out[..., 3] = arr[..., 3]
    return Image.fromarray(out, "RGBA")


def load_file(path):
    with Image.open(path) as im:
        im.load()
        return from_pil(im)


def decode_bytes(data):
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        return from_pil(im)


def encode(arr, fmt="png", quality=90):
    """Encode to bytes. JPEG has no alpha, so transparency is flattened onto white."""
    pil = to_pil(arr)
    fmt = fmt.lower()
    buf = io.BytesIO()
    if fmt in ("jpg", "jpeg"):
        bg = Image.new("RGB", pil.size, (255, 255, 255))
        bg.paste(pil, mask=pil.split()[3])
        bg.save(buf, "JPEG", quality=int(quality), optimize=True)
    elif fmt == "bmp":
        bg = Image.new("RGB", pil.size, (255, 255, 255))
        bg.paste(pil, mask=pil.split()[3])
        bg.save(buf, "BMP")
    elif fmt == "webp":
        pil.save(buf, "WEBP", quality=int(quality))
    elif fmt in ("tif", "tiff"):
        pil.save(buf, "TIFF")
    else:
        pil.save(buf, "PNG", optimize=False)
    return buf.getvalue()


def to_surface(arr):
    """Array -> cairo ImageSurface (copies)."""
    h, w = arr.shape[:2]
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    stride = surf.get_stride()
    view = np.ndarray((h, stride), dtype=np.uint8, buffer=surf.get_data())[:, : w * 4].reshape(h, w, 4)
    view[:] = arr
    surf.mark_dirty()
    return surf


def from_surface(surf, x=0, y=0, w=None, h=None):
    """cairo ImageSurface (or a region of it) -> array copy."""
    surf.flush()
    sw, sh = surf.get_width(), surf.get_height()
    w = sw - x if w is None else w
    h = sh - y if h is None else h
    x0, y0, x1, y1 = max(0, x), max(0, y), min(sw, x + w), min(sh, y + h)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((0, 0, 4), dtype=np.uint8)
    stride = surf.get_stride()
    view = np.ndarray((sh, stride), dtype=np.uint8, buffer=surf.get_data())[:, : sw * 4].reshape(sh, sw, 4)
    return view[y0:y1, x0:x1].copy()


def blank(w, h, rgba=(255, 255, 255, 255)):
    """Solid-colour premultiplied array."""
    r, g, b, a = rgba
    px = np.array([b * a // 255, g * a // 255, r * a // 255, a], dtype=np.uint8)
    return np.broadcast_to(px, (h, w, 4)).copy()


# --------------------------------------------------------------------------- whole-image effects
# Each returns a new array and never modifies its input.

def grayscale(arr):
    f = arr.astype(np.float32)
    g = 0.114 * f[..., 0] + 0.587 * f[..., 1] + 0.299 * f[..., 2]     # BGR weights (Rec.601)
    g = np.clip(np.rint(g), 0, 255).astype(np.uint8)
    out = arr.copy()
    out[..., 0] = out[..., 1] = out[..., 2] = g
    # premultiplied: grey of a premultiplied colour is already premultiplied, alpha untouched
    return out


def invert(arr):
    out = arr.copy()
    a = arr[..., 3:4]
    out[..., :3] = a - arr[..., :3]                                   # (255 - c) premultiplied == a - c_pre
    return out


def adjust(arr, brightness=1.0, contrast=1.0, gamma=1.0):
    """Greenshot's Adjust: brightness and contrast as multipliers around mid-grey, plus gamma."""
    pil = to_pil(arr)
    rgb = np.asarray(pil, dtype=np.float32)[..., :3] / 255.0
    rgb = np.clip(((rgb - 0.5) * contrast + 0.5) * brightness, 0, 1)
    if gamma != 1.0:
        rgb = np.power(rgb, 1.0 / max(gamma, 1e-3))
    out = np.asarray(pil).copy()
    out[..., :3] = np.clip(np.rint(rgb * 255), 0, 255).astype(np.uint8)
    return from_pil(Image.fromarray(out, "RGBA"))


def remove_transparency(arr, rgba=(255, 255, 255, 255)):
    bg = blank(arr.shape[1], arr.shape[0], rgba)
    a = arr[..., 3:4].astype(np.uint16)
    out = arr.astype(np.uint16) + (bg.astype(np.uint16) * (255 - a)) // 255
    out[..., 3] = 255
    return np.clip(out, 0, 255).astype(np.uint8)


def rotate90(arr, clockwise=True):
    return np.ascontiguousarray(np.rot90(arr, k=-1 if clockwise else 1))


def resize(arr, w, h):
    w, h = max(1, int(w)), max(1, int(h))
    pil = to_pil(arr).resize((w, h), Image.LANCZOS)
    return from_pil(pil)


def resize_canvas(arr, left, top, right, bottom, rgba=(0, 0, 0, 0)):
    """Grow (positive) or shrink (negative) the canvas on each side. New area is filled with ``rgba``."""
    h, w = arr.shape[:2]
    nw, nh = w + left + right, h + top + bottom
    if nw < 1 or nh < 1:
        raise ValueError("canvas would be empty")
    out = blank(nw, nh, rgba)
    sx0, sy0 = max(0, -left), max(0, -top)
    dx0, dy0 = max(0, left), max(0, top)
    cw, ch = min(w - sx0, nw - dx0), min(h - sy0, nh - dy0)
    out[dy0:dy0 + ch, dx0:dx0 + cw] = arr[sy0:sy0 + ch, sx0:sx0 + cw]
    return out


def add_border(arr, width=2, rgba=(0, 0, 0, 255)):
    """Greenshot's Add border: grows the canvas by ``width`` on every side and fills the ring."""
    width = max(0, int(width))
    return resize_canvas(arr, width, width, width, width, rgba) if width else arr.copy()


def drop_shadow(arr, offset=(5, 5), darkness=0.6, blur_radius=6, background=(0, 0, 0, 0), return_offset=False):
    """Greenshot's Drop shadow: soft shadow of the image's shape, canvas grown to fit it."""
    dx, dy = offset
    m = blur_radius + 1
    left, top = m + max(-dx, 0), m + max(-dy, 0)
    right, bottom = m + max(dx, 0), m + max(dy, 0)
    big = resize_canvas(arr, left, top, right, bottom, background)
    h, w = big.shape[:2]
    alpha = np.zeros((h, w, 4), dtype=np.uint8)
    alpha[top + dy:top + dy + arr.shape[0], left + dx:left + dx + arr.shape[1], 3] = arr[..., 3]
    soft = fx.blur(alpha, max(1, blur_radius // 2)) if blur_radius > 0 else alpha
    sh = np.zeros_like(soft)
    sh[..., 3] = np.clip(soft[..., 3].astype(np.float32) * darkness, 0, 255).astype(np.uint8)  # black, premultiplied
    # shadow first, then the image on top
    out = sh.astype(np.uint16)
    a = big[..., 3:4].astype(np.uint16)
    out = big.astype(np.uint16) + (out * (255 - a)) // 255
    out = np.clip(out, 0, 255).astype(np.uint8)
    return (out, (left, top)) if return_offset else out


def torn_edge(arr, tooth_height=12, tooth_range=20, edges=(True, True, True, True), seed=None,
              shadow=True, offset=(4, 4), darkness=0.5, blur_radius=6, return_offset=False):
    """Greenshot's Torn edge: jagged random edges on the chosen sides (top, right, bottom, left)."""
    rng = np.random.default_rng(seed)
    h, w = arr.shape[:2]
    out = arr.copy()
    mask = np.ones((h, w), dtype=bool)
    th = max(2, int(tooth_height))

    def profile(n):
        """Random zig-zag depth along an edge of length n, each tooth 'tooth_range' px at most."""
        pts, pos = [], 0
        while pos < n:
            pts.append((pos, rng.integers(0, th + 1)))
            pos += int(rng.integers(max(2, tooth_range // 2), max(3, tooth_range) + 1))
        pts.append((n, pts[0][1]))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return np.rint(np.interp(np.arange(n), xs, ys)).astype(int)

    top_e, right_e, bottom_e, left_e = edges
    if top_e:
        d = profile(w)
        for x in range(w):
            mask[: d[x], x] = False
    if bottom_e:
        d = profile(w)
        for x in range(w):
            if d[x]:
                mask[h - d[x]:, x] = False
    if left_e:
        d = profile(h)
        for y in range(h):
            mask[y, : d[y]] = False
    if right_e:
        d = profile(h)
        for y in range(h):
            if d[y]:
                mask[y, w - d[y]:] = False
    out[~mask] = 0
    if shadow:
        return drop_shadow(out, offset, darkness, blur_radius, return_offset=return_offset)
    return (out, (0, 0)) if return_offset else out


def auto_crop_box(arr, tolerance=0):
    """Bounding box (x, y, w, h) of everything that differs from the colour of the top-left pixel."""
    h, w = arr.shape[:2]
    if h == 0 or w == 0:
        return (0, 0, w, h)
    bg = arr[0, 0].astype(np.int16)
    diff = np.abs(arr.astype(np.int16) - bg).max(axis=2) > tolerance
    rows, cols = np.where(diff.any(axis=1))[0], np.where(diff.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return (0, 0, w, h)
    return (int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))


def composite(base, sprite, x, y):
    """Draw a premultiplied-BGRA sprite onto a copy of ``base`` at (x, y), clipped to the image."""
    out = base.copy()
    h, w = base.shape[:2]
    sh, sw = sprite.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + sw), min(h, y + sh)
    if x1 <= x0 or y1 <= y0:
        return out
    s = sprite[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.uint16)
    d = out[y0:y1, x0:x1].astype(np.uint16)
    out[y0:y1, x0:x1] = np.clip(s + d * (255 - s[..., 3:4]) // 255, 0, 255).astype(np.uint8)
    return out
