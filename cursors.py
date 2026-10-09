"""Mouse-cursor images from the user's installed cursor theme (libXcursor via ctypes, no extra packages).

Used for Greenshot's "insert mouse cursor": the sprite is an ordinary movable image object in the editor.
Pixels come back as premultiplied BGRA, the same layout as everything else in Snipshot.
"""
import ctypes

import numpy as np

SHAPES = {
    "arrow": ["left_ptr", "default", "arrow", "top_left_arrow"],
    "hand": ["hand2", "pointer", "hand1", "pointing_hand"],
    "text": ["xterm", "text", "ibeam"],
    "crosshair": ["crosshair", "cross", "tcross"],
    "busy": ["watch", "wait", "left_ptr_watch"],
}
LABELS = {"arrow": "Arrow", "hand": "Hand", "text": "Text (I-beam)", "crosshair": "Crosshair", "busy": "Busy"}


class _XcursorImage(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("size", ctypes.c_uint32), ("width", ctypes.c_uint32),
                ("height", ctypes.c_uint32), ("xhot", ctypes.c_uint32), ("yhot", ctypes.c_uint32),
                ("delay", ctypes.c_uint32), ("pixels", ctypes.POINTER(ctypes.c_uint32))]


_lib = None


def _xcursor():
    global _lib
    if _lib is None:
        lib = ctypes.CDLL("libXcursor.so.1")
        lib.XcursorLibraryLoadImage.restype = ctypes.POINTER(_XcursorImage)
        lib.XcursorLibraryLoadImage.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        lib.XcursorImageDestroy.argtypes = [ctypes.POINTER(_XcursorImage)]
        _lib = lib
    return _lib


def theme_settings():
    """(theme name, size) from the desktop settings, with sensible defaults."""
    try:
        from gi.repository import Gio
        s = Gio.Settings.new("org.gnome.desktop.interface")
        return s.get_string("cursor-theme") or None, int(s.get_int("cursor-size")) or 24
    except Exception:                                   # noqa: BLE001 - any failure just means 'use defaults'
        return None, 24


def load(shape="arrow", size=None, theme=None):
    """(BGRA premultiplied array, hotspot_x, hotspot_y) for a cursor shape, or None if no theme has it."""
    th, sz = theme_settings()
    theme, size = theme or th, size or sz
    try:
        lib = _xcursor()
    except OSError:
        return None
    for name in SHAPES.get(shape, [shape]):
        for t in ([theme] if theme else []) + [None]:
            ptr = lib.XcursorLibraryLoadImage(name.encode(), t.encode() if t else None, int(size))
            if not ptr:
                continue
            img = ptr.contents
            w, h = img.width, img.height
            if w and h:
                px = np.ctypeslib.as_array(img.pixels, shape=(w * h,)).copy()
                arr = px.view(np.uint8).reshape(h, w, 4)
                hot = (int(img.xhot), int(img.yhot))
                lib.XcursorImageDestroy(ptr)
                return arr, hot[0], hot[1]
            lib.XcursorImageDestroy(ptr)
    return None


def fallback_arrow(size=24):
    """A plain black-and-white arrow, used only when the theme cannot be read."""
    from PIL import Image, ImageDraw
    import imaging as im
    s = size
    img = Image.new("RGBA", (s, int(s * 1.5)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(1, 1), (1, int(s * 1.2)), (int(s * 0.32), int(s * 0.95)), (int(s * 0.55), int(s * 1.4)),
           (int(s * 0.72), int(s * 1.32)), (int(s * 0.5), int(s * 0.9)), (int(s * 0.85), int(s * 0.88))]
    d.polygon(pts, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
    return im.from_pil(img), 1, 1


def get(shape="arrow", size=None):
    return load(shape, size) or (fallback_arrow(size or 24) if shape == "arrow" else load("arrow", size)) \
        or fallback_arrow(size or 24)
