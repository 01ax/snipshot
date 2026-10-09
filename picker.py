"""Greenshot-style "what do you want to do with the screenshot?" picker.

Shown after a capture when the preference is "ask". Pick a destination and it runs; close the window or press
Esc without choosing and the screenshot is simply discarded (nothing is saved or copied).
"""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk  # noqa: E402

import imaging as im  # noqa: E402

# (key, label, mnemonic key) in Greenshot's order: editor first, then the quick destinations
DESTINATIONS = [
    ("editor", "Open in image editor", Gdk.KEY_e),
    ("clipboard", "Copy to clipboard", Gdk.KEY_c),
    ("save", "Save directly (using preferred file output settings)", Gdk.KEY_s),
    ("save_as", "Save as...", Gdk.KEY_a),
    ("print", "Print...", Gdk.KEY_p),
    ("email", "E-mail...", Gdk.KEY_m),
]
ICONS = {"editor": "document-edit-symbolic", "clipboard": "edit-copy-symbolic", "save": "document-save-symbolic",
         "save_as": "document-save-as-symbolic", "print": "document-print-symbolic", "email": "mail-send-symbolic"}


def logical_size(w, h, max_w=440, max_h=270):
    """The size the preview is SHOWN at (logical pixels): the capture scaled down to fit, never enlarged."""
    s = min(max_w / w, max_h / h, 1.0)
    return max(1, round(w * s)), max(1, round(h * s))


class Thumb(Gtk.Widget):
    """The capture, scaled down to a small size on screen but kept at full sharpness.

    The preview used to be shrunk to its on-screen size in logical pixels, so on a scaled (e.g. 1.5x) monitor the
    desktop then enlarged it again and it looked soft. Now it is shrunk to the number of real (physical) pixels it
    will occupy, and drawn at its logical size, so every physical pixel of the preview is real picture."""
    __gtype_name__ = "SnipshotThumb"

    def __init__(self, arr, max_w=440, max_h=270):
        super().__init__()
        self.arr = arr
        h, w = arr.shape[:2]
        self.lw, self.lh = logical_size(w, h, max_w, max_h)
        self._textures = {}
        self.connect("notify::scale-factor", lambda *_: self.queue_draw())

    @staticmethod
    def physical_size(arr_w, arr_h, lw, lh, scale):
        """Pixels the preview should have for a monitor scale: the on-screen size times the scale, but never more than
        the capture itself has."""
        f = min(1.0, (lw * scale) / arr_w, (lh * scale) / arr_h)
        return max(1, round(arr_w * f)), max(1, round(arr_h * f))

    def texture(self, scale):
        if scale not in self._textures:
            h, w = self.arr.shape[:2]
            pw, ph = self.physical_size(w, h, self.lw, self.lh, scale)
            small = im.resize(self.arr, pw, ph) if (pw, ph) != (w, h) else self.arr
            import io
            buf = io.BytesIO()
            im.to_pil(small).save(buf, "PNG")
            self._textures[scale] = Gdk.Texture.new_from_bytes(GLib.Bytes.new(buf.getvalue()))
        return self._textures[scale]

    def do_measure(self, orientation, for_size):
        n = self.lw if orientation == Gtk.Orientation.HORIZONTAL else self.lh
        return n, n, -1, -1

    def do_snapshot(self, snapshot):
        rect = Graphene.Rect()
        rect.init(0, 0, self.lw, self.lh)
        snapshot.append_scaled_texture(self.texture(max(1, self.get_scale_factor())), Gsk.ScalingFilter.TRILINEAR, rect)


def thumbnail(arr, max_w=360, max_h=210):
    """A Gdk.Texture preview of the capture at its on-screen size (kept for callers that want a plain texture)."""
    h, w = arr.shape[:2]
    lw, lh = logical_size(w, h, max_w, max_h)
    small = im.resize(arr, lw, lh) if (lw, lh) != (w, h) else arr
    import io
    buf = io.BytesIO()
    im.to_pil(small).save(buf, "PNG")
    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(buf.getvalue()))


class Picker(Gtk.Window):
    """``on_choice(key)`` is called with a destination key, or None when the user discards the capture.
    The window stays open until a destination reports success (``done(True)``) or the user discards."""

    def __init__(self, arr, on_choice, size_text=""):
        super().__init__(title="Snipshot - what to do with the screenshot?", resizable=False)
        self.on_choice = on_choice
        self._finished = False
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=14, margin_bottom=14,
                      margin_start=16, margin_end=16)
        self.set_child(box)
        self.thumb = Thumb(arr)
        frame = Gtk.Frame(halign=Gtk.Align.CENTER)
        frame.set_child(self.thumb)
        frame.add_css_class("picker-thumb")
        box.append(frame)
        if size_text:
            box.append(Gtk.Label(label=size_text, css_classes=["dim-label"]))
        self.buttons = []
        for key, label, mnem in DESTINATIONS:
            b = Gtk.Button()
            row = Gtk.Box(spacing=10)
            row.append(Gtk.Image.new_from_icon_name(ICONS[key]))
            lab = Gtk.Label(label=label, xalign=0, hexpand=True)
            row.append(lab)
            row.append(Gtk.Label(label=Gdk.keyval_name(mnem).upper(), css_classes=["dim-label"]))
            b.set_child(row)
            b.connect("clicked", lambda _b, k=key: self._pick(k))
            box.append(b)
            self.buttons.append(b)
        hint = Gtk.Label(label="Esc (or closing this window) discards the screenshot", css_classes=["dim-label"])
        box.append(hint)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self.connect("close-request", self._closing)
        self.buttons[0].grab_focus()

    def _key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        low = Gdk.keyval_to_lower(keyval)
        for key, _label, mnem in DESTINATIONS:
            if low == mnem:
                self._pick(key)
                return True
        return False

    def _pick(self, key):
        if self._finished:
            return
        self.set_sensitive(False)
        self.on_choice(key, self._result)

    def _result(self, ok):
        """Called by the app when the chosen destination finished: success closes the picker, failure re-opens it."""
        if self._finished:
            return
        if ok:
            self._finished = True
            self.close()
        else:
            self.set_sensitive(True)
            self.present()

    def _closing(self, *_):
        if not self._finished:
            self._finished = True
            self.on_choice(None, lambda ok: None)          # discarded
        return False
