"""Small dialogs for Snipshot: resize, canvas size, border, shadow, torn edge, adjust, about.

Dialogs are NOT marked modal: GNOME's attach-modal-dialogs setting pins modal dialogs to their parent so they
cannot be dragged. Instead the parent's content is made untargetable while a dialog is open.
"""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402


class Dialog(Gtk.Window):
    def __init__(self, parent, title, width=380):
        super().__init__(title=title, transient_for=parent, modal=False, destroy_with_parent=True, resizable=False)
        self.set_default_size(width, -1)
        self._parent = parent
        parent._blocks = getattr(parent, "_blocks", 0) + 1
        if parent.get_child() is not None:
            parent.get_child().set_can_target(False)
        self.connect("close-request", self._release)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=14, margin_bottom=14,
                           margin_start=16, margin_end=16)
        self.set_child(self.box)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, k, *_: (self.close(), True)[1] if k == Gdk.KEY_Escape else False)
        self.add_controller(keys)

    def _release(self, *_):
        p, self._parent = self._parent, None
        if p is not None:
            p._blocks -= 1
            if p._blocks <= 0 and p.get_child() is not None:
                p.get_child().set_can_target(True)
        return False

    def buttons(self, ok_label, on_ok, cancel=True):
        row = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=6)
        if cancel:
            c = Gtk.Button(label="Cancel")
            c.connect("clicked", lambda *_: self.close())
            row.append(c)
        ok = Gtk.Button(label=ok_label)
        ok.add_css_class("suggested-action")
        ok.connect("clicked", lambda *_: on_ok())
        row.append(ok)
        self.box.append(row)
        self.set_default_widget(ok)
        return ok


def _spin(lo, hi, val, step=1, digits=0):
    s = Gtk.SpinButton.new_with_range(lo, hi, step)
    s.set_digits(digits)
    s.set_value(val)
    s.set_hexpand(True)
    return s


def _row(grid, r, label, widget):
    lb = Gtk.Label(label=label, xalign=0)
    grid.attach(lb, 0, r, 1, 1)
    grid.attach(widget, 1, r, 1, 1)
    return widget


def _grid():
    return Gtk.Grid(column_spacing=12, row_spacing=8)


def _color_button(rgba=(0, 0, 0, 1)):
    b = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=True))
    b.set_rgba(Gdk.RGBA(*rgba))
    return b


def _rgba255(b):
    c = b.get_rgba()
    return tuple(int(round(v * 255)) for v in (c.red, c.green, c.blue, c.alpha))


# --------------------------------------------------------------------------- the dialogs

def resize_dialog(parent, w, h, on_ok):
    d = Dialog(parent, "Resize image")
    g = _grid()
    d.box.append(g)
    mode = Gtk.DropDown.new_from_strings(["Percent", "Pixels"])
    _row(g, 0, "Resize by", mode)
    pw = _row(g, 1, "Width", _spin(1, 20000, 100))
    ph = _row(g, 2, "Height", _spin(1, 20000, 100))
    keep = Gtk.CheckButton(label="Keep aspect ratio")
    keep.set_active(True)
    g.attach(keep, 1, 3, 1, 1)
    state = {"busy": False}

    def sync_mode(*_):
        state["busy"] = True
        if mode.get_selected() == 0:
            pw.set_range(1, 1000); ph.set_range(1, 1000); pw.set_value(100); ph.set_value(100)
        else:
            pw.set_range(1, 20000); ph.set_range(1, 20000); pw.set_value(w); ph.set_value(h)
        state["busy"] = False

    def link(src, dst, ratio):
        def f(*_):
            if state["busy"] or not keep.get_active():
                return
            state["busy"] = True
            dst.set_value(round(src.get_value() * ratio))
            state["busy"] = False
        return f
    mode.connect("notify::selected", sync_mode)
    pw.connect("value-changed", lambda *_: link(pw, ph, (h / w) if mode.get_selected() else 1.0)())
    ph.connect("value-changed", lambda *_: link(ph, pw, (w / h) if mode.get_selected() else 1.0)())

    def ok():
        if mode.get_selected() == 0:
            nw, nh = round(w * pw.get_value() / 100), round(h * ph.get_value() / 100)
        else:
            nw, nh = int(pw.get_value()), int(ph.get_value())
        d.close()
        on_ok(max(1, nw), max(1, nh))
    d.buttons("Resize", ok)
    d.present()


def canvas_dialog(parent, on_ok):
    d = Dialog(parent, "Resize canvas")
    g = _grid()
    d.box.append(g)
    d.box.prepend(Gtk.Label(label="Pixels to add (negative removes) on each side:", xalign=0))
    fields = {n: _row(g, i, n, _spin(-20000, 20000, 0)) for i, n in enumerate(("Left", "Top", "Right", "Bottom"))}
    col = _row(g, 4, "Fill colour", _color_button((1, 1, 1, 0)))

    def ok():
        d.close()
        on_ok(*(int(fields[n].get_value()) for n in ("Left", "Top", "Right", "Bottom")), _rgba255(col))
    d.buttons("Apply", ok)
    d.present()


def border_dialog(parent, on_ok):
    d = Dialog(parent, "Add border")
    g = _grid()
    d.box.append(g)
    wd = _row(g, 0, "Width (px)", _spin(1, 200, 2))
    col = _row(g, 1, "Colour", _color_button((0, 0, 0, 1)))
    d.buttons("Add border", lambda: (d.close(), on_ok(int(wd.get_value()), _rgba255(col))))
    d.present()


def shadow_dialog(parent, on_ok):
    d = Dialog(parent, "Drop shadow")
    g = _grid()
    d.box.append(g)
    ox = _row(g, 0, "Offset X", _spin(-50, 50, 5))
    oy = _row(g, 1, "Offset Y", _spin(-50, 50, 5))
    bl = _row(g, 2, "Blur", _spin(0, 60, 6))
    dk = _row(g, 3, "Darkness %", _spin(5, 100, 60))
    d.buttons("Add shadow", lambda: (d.close(), on_ok((int(ox.get_value()), int(oy.get_value())),
                                                       int(bl.get_value()), dk.get_value() / 100)))
    d.present()


def torn_dialog(parent, on_ok):
    d = Dialog(parent, "Torn edge")
    g = _grid()
    d.box.append(g)
    th = _row(g, 0, "Tooth height", _spin(2, 100, 12))
    tr = _row(g, 1, "Horizontal range", _spin(4, 200, 20))
    edges = {}
    box = Gtk.Box(spacing=10)
    for name in ("Top", "Right", "Bottom", "Left"):
        c = Gtk.CheckButton(label=name)
        c.set_active(True)
        edges[name] = c
        box.append(c)
    _row(g, 2, "Edges", box)
    sh = Gtk.CheckButton(label="Generate shadow")
    sh.set_active(True)
    g.attach(sh, 1, 3, 1, 1)
    d.buttons("Apply", lambda: (d.close(), on_ok(int(th.get_value()), int(tr.get_value()),
                                                  tuple(edges[n].get_active() for n in ("Top", "Right", "Bottom", "Left")),
                                                  sh.get_active())))
    d.present()


def adjust_dialog(parent, on_preview, on_ok, on_cancel):
    """Brightness / contrast / gamma with a live preview; Cancel restores the original."""
    d = Dialog(parent, "Adjust colours", 420)
    g = _grid()
    d.box.append(g)

    def slider(row, label, lo, hi, val):
        s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 0.01)
        s.set_value(val)
        s.set_hexpand(True)
        s.set_draw_value(True)
        s.set_digits(2)
        _row(g, row, label, s)
        return s
    br = slider(0, "Brightness", 0.2, 2.0, 1.0)
    co = slider(1, "Contrast", 0.2, 2.0, 1.0)
    ga = slider(2, "Gamma", 0.3, 3.0, 1.0)
    vals = lambda: (br.get_value(), co.get_value(), ga.get_value())   # noqa: E731
    for s in (br, co, ga):
        s.connect("value-changed", lambda *_: on_preview(*vals()))

    def cancel():
        on_cancel()
    d.connect("close-request", lambda *_: (cancel() if not d.__dict__.get("applied") else None, False)[1])

    def ok():
        d.applied = True
        d.close()
        on_ok(*vals())
    d.buttons("Apply", ok)
    d.present()


def about_dialog(parent, version):
    d = Gtk.AboutDialog(transient_for=parent, modal=False)
    d.set_program_name("Snipshot")
    d.set_version(version)
    d.set_comments("A screenshot tool and annotation editor for Linux, modelled on Greenshot's workflow.\n"
                   "Pixelate and blur are regular, adjustable effects.")
    d.set_license_type(Gtk.License.CUSTOM)
    d.set_license("Personal project. Behaviour modelled on Greenshot; contains none of its code.")
    d.set_logo_icon_name("snipshot")
    d.present()


class OcrResultWindow(Gtk.Window):
    """Shows the text found by OCR and puts it on the clipboard.

    A window (rather than a silent background copy) because GNOME only lets a program that has a focused window set
    the clipboard: a background daemon whose overlay has just closed is ignored. The text can be corrected here and
    copied again."""

    def __init__(self, text, copy_text, title="Text from the screen"):
        super().__init__(title=title, default_width=480, default_height=260)
        self._copy_text = copy_text
        self._first = True
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12, margin_start=14, margin_end=14)
        self.set_child(box)
        self.status = Gtk.Label(xalign=0)
        self.status.add_css_class("dim-label")
        box.append(self.status)
        self.buffer = Gtk.TextBuffer()
        self.buffer.set_text(text)
        view = Gtk.TextView(buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=6, right_margin=6, top_margin=6,
                            bottom_margin=6, monospace=True)
        scroll = Gtk.ScrolledWindow(vexpand=True, child=view)
        scroll.add_css_class("card")
        box.append(scroll)
        row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        copy = Gtk.Button(label="Copy again")
        copy.connect("clicked", lambda *_: self.copy())
        close = Gtk.Button(label="Close")
        close.add_css_class("suggested-action")
        close.connect("clicked", lambda *_: self.close())
        row.append(copy)
        row.append(close)
        box.append(row)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, k, *_: (self.close(), True)[1] if k == Gdk.KEY_Escape else False)
        self.add_controller(keys)
        self.connect("notify::is-active", self._on_active)
        self._update_status(False)

    def _on_active(self, *_):
        if self._first and self.is_active():              # the first moment this window has focus: now the copy is accepted
            self._first = False
            self.copy()

    def text(self):
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False)

    def copy(self):
        self._copy_text(self.text())
        self._update_status(True)

    def _update_status(self, copied):
        n = len(self.text())
        self.status.set_text(f"{n} characters" + (" - copied to the clipboard" if copied else ""))
