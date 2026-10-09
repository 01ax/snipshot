"""Greenshot-style "what do you want to do with the screenshot?" picker.

Shown after a capture when the preference is "ask". Pick a destination and it runs; close the window or press
Esc without choosing and the screenshot is simply discarded (nothing is saved or copied).
"""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

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


def thumbnail(arr, max_w=360, max_h=210):
    """A small Gdk.Texture preview of the capture."""
    h, w = arr.shape[:2]
    s = min(max_w / w, max_h / h, 1.0)
    small = im.resize(arr, max(1, int(w * s)), max(1, int(h * s))) if s < 1.0 else arr
    pil = im.to_pil(small)
    import io
    buf = io.BytesIO()
    pil.save(buf, "PNG")
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
        pic = Gtk.Picture.new_for_paintable(thumbnail(arr))
        pic.set_can_shrink(False)
        pic.add_css_class("picker-thumb")
        box.append(pic)
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
