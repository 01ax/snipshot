"""The Snipshot editor window: menus, toolbars, tools, property bar, status bar and every action."""
import copy
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, PangoCairo  # noqa: E402

import canvas as CV  # noqa: E402
import config as CFG  # noqa: E402
import dialogs as DLG  # noqa: E402
import icons  # noqa: E402
import imaging as im  # noqa: E402
import model as M  # noqa: E402
import output  # noqa: E402


TOOL_KEYS = {"r": "rect", "e": "ellipse", "l": "line", "f": "freehand", "a": "arrow", "t": "text", "s": "speech",
             "i": "step", "h": "highlight", "o": "obfuscate", "c": "crop"}
TOOL_LABELS = [("select", "Select (Esc)"), ("rect", "Rectangle (R)"), ("ellipse", "Ellipse (E)"),
               ("line", "Line (L)"), ("arrow", "Arrow (A)"), ("freehand", "Freehand (F)"), ("text", "Text (T)"),
               ("speech", "Speech bubble (S)"), ("step", "Step label (I)"), ("obfuscate", "Obfuscate (O)"),
               ("highlight", "Highlight (H)"), ("crop", "Crop (C)")]
ZOOM_ITEMS = ["Best fit", "25%", "50%", "66%", "75%", "100%", "200%", "300%", "400%", "600%"]


def _rgba(c):
    return Gdk.RGBA(*c)


def _tuple(rgba):
    return (rgba.red, rgba.green, rgba.blue, rgba.alpha)


def font_families():
    names = sorted({f.get_name() for f in PangoCairo.FontMap.get_default().list_families()}, key=str.lower)
    first = ["Sans", "Serif", "Monospace"]
    return first + [n for n in names if n not in first]


# =============================================================================== property bar

class PropBar(Gtk.Box):
    """Context-sensitive object properties, like Greenshot's property toolbar."""

    def __init__(self, canvas, window):
        super().__init__(spacing=14)
        self.canvas = canvas
        self.window = window
        self._busy = False
        self.add_css_class("propbar")
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.groups = {}

        def group(name):
            g = Gtk.Box(spacing=6)
            self.groups[name] = g
            self.append(g)
            return g

        def lbl(g, text):
            g.append(Gtk.Label(label=text))

        # fill
        g = group("fill")
        lbl(g, "Fill")
        self.fill = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=True))
        self.fill.set_tooltip_text("Fill colour")
        self.fill.connect("notify::rgba", lambda *_: self._set("fill_color", _tuple(self.fill.get_rgba())))
        g.append(self.fill)
        self.nofill = Gtk.Button(label="None")
        self.nofill.set_tooltip_text("No fill (transparent)")
        self.nofill.connect("clicked", lambda *_: self._set("fill_color", M.TRANSPARENT))
        g.append(self.nofill)
        # line
        g = group("line")
        lbl(g, "Line")
        self.line = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=True))
        self.line.set_tooltip_text("Line / text colour")
        self.line.connect("notify::rgba", lambda *_: self._set("line_color", _tuple(self.line.get_rgba())))
        g.append(self.line)
        lbl(g, "Thickness")
        self.thick = Gtk.SpinButton.new_with_range(0, 40, 1)
        self.thick.connect("value-changed", lambda *_: self._set("thickness", int(self.thick.get_value())))
        g.append(self.thick)
        # shadow
        g = group("shadow")
        self.shadow = Gtk.CheckButton(label="Shadow")
        self.shadow.connect("toggled", lambda *_: self._set("shadow", self.shadow.get_active()))
        g.append(self.shadow)
        # font
        g = group("font")
        self.families = font_families()
        self.font = Gtk.DropDown.new_from_strings(self.families)
        self.font.set_enable_search(False)
        self.font.connect("notify::selected", lambda *_: self._set("font", self.families[self.font.get_selected()]))
        g.append(self.font)
        self.fsize = Gtk.SpinButton.new_with_range(5, 300, 1)
        self.fsize.connect("value-changed", lambda *_: self._set("font_size", float(self.fsize.get_value())))
        g.append(self.fsize)
        self.bold = Gtk.ToggleButton(label="B")
        self.bold.add_css_class("bold-btn")
        self.bold.connect("toggled", lambda *_: self._set("bold", self.bold.get_active()))
        g.append(self.bold)
        self.italic = Gtk.ToggleButton(label="I")
        self.italic.add_css_class("italic-btn")
        self.italic.connect("toggled", lambda *_: self._set("italic", self.italic.get_active()))
        g.append(self.italic)
        self.halign = Gtk.DropDown.new_from_strings(["Left", "Center", "Right"])
        self.halign.connect("notify::selected", lambda *_: self._set("halign", ("left", "center", "right")[self.halign.get_selected()]))
        g.append(self.halign)
        self.valign = Gtk.DropDown.new_from_strings(["Top", "Middle", "Bottom"])
        self.valign.connect("notify::selected", lambda *_: self._set("valign", ("top", "middle", "bottom")[self.valign.get_selected()]))
        g.append(self.valign)
        # arrow heads
        g = group("arrow")
        lbl(g, "Arrow heads")
        self.heads = Gtk.DropDown.new_from_strings(["None", "Start", "End", "Both"])
        self.heads.connect("notify::selected", lambda *_: self._set(
            "arrowheads", (M.ARROW_NONE, M.ARROW_START, M.ARROW_END, M.ARROW_BOTH)[self.heads.get_selected()]))
        g.append(self.heads)
        # obfuscate
        g = group("obf")
        lbl(g, "Mode")
        self.obf_mode = Gtk.DropDown.new_from_strings(["Pixelize", "Blur"])
        self.obf_mode.connect("notify::selected", lambda *_: self._set("preset", ("pixelize", "blur")[self.obf_mode.get_selected()]))
        g.append(self.obf_mode)
        self.px_box = Gtk.Box(spacing=6)
        self.px_box.append(Gtk.Label(label="Pixel size"))
        self.px = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 2, 100, 1)
        self.px.set_size_request(170, -1)
        self.px.set_draw_value(True)
        self.px.set_digits(0)
        self.px.set_value_pos(Gtk.PositionType.RIGHT)
        self.px.connect("value-changed", lambda *_: self._set("pixel_size", int(self.px.get_value())))
        self.px_box.append(self.px)
        self.rand = Gtk.CheckButton(label="Randomise blocks")
        self.rand.set_tooltip_text("Irregular block sizes: looks less tidy but is harder to reverse")
        self.rand.connect("toggled", lambda *_: self._set("randomise", self.rand.get_active()))
        self.px_box.append(self.rand)
        g.append(self.px_box)
        self.bl_box = Gtk.Box(spacing=6)
        self.bl_box.append(Gtk.Label(label="Blur radius"))
        self.bl = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        self.bl.set_size_request(170, -1)
        self.bl.set_draw_value(True)
        self.bl.set_digits(0)
        self.bl.set_value_pos(Gtk.PositionType.RIGHT)
        self.bl.connect("value-changed", lambda *_: self._set("blur_radius", int(self.bl.get_value())))
        self.bl_box.append(self.bl)
        g.append(self.bl_box)
        # highlight
        g = group("hl")
        lbl(g, "Mode")
        self.hl_mode = Gtk.DropDown.new_from_strings(["Text highlight", "Area highlight", "Grayscale", "Magnify"])
        self.hl_mode.connect("notify::selected", lambda *_: self._set("preset", ("text", "area", "gray", "magnify")[self.hl_mode.get_selected()]))
        g.append(self.hl_mode)
        self.mag_box = Gtk.Box(spacing=6)
        self.mag_box.append(Gtk.Label(label="Magnification"))
        self.mag = Gtk.SpinButton.new_with_range(1, 10, 0.5)
        self.mag.set_digits(1)
        self.mag.connect("value-changed", lambda *_: self._set("magnification", float(self.mag.get_value())))
        self.mag_box.append(self.mag)
        g.append(self.mag_box)
        self.br_box = Gtk.Box(spacing=6)
        self.br_box.append(Gtk.Label(label="Brightness"))
        self.br = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.1, 1.0, 0.05)
        self.br.set_size_request(120, -1)
        self.br.set_draw_value(True)
        self.br.set_digits(2)
        self.br.connect("value-changed", lambda *_: self._set("brightness", round(self.br.get_value(), 2)))
        self.br_box.append(self.br)
        g.append(self.br_box)
        # step label counter
        g = group("step")
        lbl(g, "Counter start")
        self.counter = Gtk.SpinButton.new_with_range(0, 9999, 1)
        self.counter.connect("value-changed", self._counter_changed)
        g.append(self.counter)
        # crop
        g = group("crop")
        self.crop_mode = Gtk.DropDown.new_from_strings(["Crop", "Cut out vertical strip", "Cut out horizontal strip"])
        self.crop_mode.connect("notify::selected", self._crop_mode)
        g.append(self.crop_mode)
        auto = Gtk.Button(label="Auto-crop")
        auto.set_tooltip_text("Crop away the uniform border")
        auto.connect("clicked", lambda *_: canvas.crop_auto())
        g.append(auto)
        ok = Gtk.Button(label="Apply (Enter)")
        ok.add_css_class("suggested-action")
        ok.connect("clicked", lambda *_: window.confirm_crop())
        g.append(ok)
        cancel = Gtk.Button(label="Cancel (Esc)")
        cancel.connect("clicked", lambda *_: window.cancel_crop())
        g.append(cancel)

    # -- control -> canvas
    def _set(self, name, value):
        if self._busy:
            return
        self.canvas.set_prop(name, value)
        self.refresh()

    def _counter_changed(self, *_):
        if self._busy:
            return
        self.canvas.scene.counter_start = int(self.counter.get_value())
        self.canvas.scene.touch()
        self.canvas.area.queue_draw()
        self.canvas.modified = True
        self.canvas.on_changed()

    def _crop_mode(self, *_):
        if self._busy:
            return
        mode = ("default", "vertical", "horizontal")[self.crop_mode.get_selected()]
        self.canvas.defaults["crop"]["mode"] = mode
        if self.canvas.crop is not None:
            self.canvas.crop.p["mode"] = mode
            self.canvas.area.queue_draw()

    # -- canvas -> controls
    def refresh(self):
        c = self.canvas
        kinds = c.selected_kinds()
        crop = c.tool == "crop"
        show = lambda name, cond: self.groups[name].set_visible(bool(cond))     # noqa: E731
        show("fill", kinds & {"rect", "ellipse", "text", "speech", "step", "highlight"})
        show("line", kinds & {"rect", "ellipse", "line", "arrow", "freehand", "text", "speech", "step"})
        show("shadow", kinds & {"rect", "ellipse", "line", "arrow", "text", "speech", "step"})
        show("font", kinds & {"text", "speech"})
        show("arrow", "arrow" in kinds)
        show("obf", "obfuscate" in kinds)
        show("hl", "highlight" in kinds)
        show("step", "step" in kinds)
        show("crop", crop)
        self._busy = True
        try:
            g = c.get_prop
            if g("fill_color") is not None:
                self.fill.set_rgba(_rgba(g("fill_color")))
            if g("line_color") is not None:
                self.line.set_rgba(_rgba(g("line_color")))
            if g("thickness") is not None:
                self.thick.set_value(g("thickness"))
            self.shadow.set_active(bool(g("shadow", False)))
            fam = g("font", "Sans")
            if fam in self.families:
                self.font.set_selected(self.families.index(fam))
            self.fsize.set_value(g("font_size", 11))
            self.bold.set_active(bool(g("bold", False)))
            self.italic.set_active(bool(g("italic", False)))
            self.halign.set_selected(("left", "center", "right").index(g("halign", "center")))
            self.valign.set_selected(("top", "middle", "bottom").index(g("valign", "middle")))
            self.heads.set_selected((M.ARROW_NONE, M.ARROW_START, M.ARROW_END, M.ARROW_BOTH).index(g("arrowheads", M.ARROW_END)))
            preset = g("preset", "pixelize") if "obfuscate" in kinds else "pixelize"
            self.obf_mode.set_selected(1 if preset == "blur" else 0)
            self.px_box.set_visible(preset != "blur")
            self.bl_box.set_visible(preset == "blur")
            self.px.set_value(g("pixel_size", 10) or 10)
            self.bl.set_value(g("blur_radius", 10) or 10)
            self.rand.set_active(bool(g("randomise", False)))
            hp = g("preset", "text") if "highlight" in kinds else "text"
            self.hl_mode.set_selected(("text", "area", "gray", "magnify").index(hp) if hp in ("text", "area", "gray", "magnify") else 0)
            self.mag_box.set_visible(hp == "magnify")
            self.br_box.set_visible(hp == "area")
            self.mag.set_value(g("magnification", 2) or 2)
            self.br.set_value(g("brightness", 0.5) or 0.5)
            self.counter.set_value(c.scene.counter_start)
            cm = c.crop.p.get("mode", "default") if c.crop else c.defaults["crop"].get("mode", "default")
            self.crop_mode.set_selected(("default", "vertical", "horizontal").index(cm))
            self.set_visible(any(gr.get_visible() for gr in self.groups.values()))
        finally:
            self._busy = False


# =============================================================================== editor window

class EditorWindow(Gtk.ApplicationWindow):
    def __init__(self, app, scene, cfg, name="", path=None):
        super().__init__(application=app)
        self.app = app
        self.cfg = cfg
        self.path = path
        self.title_hint = name
        self.canvas = CV.Canvas(scene, cfg)
        self.set_icon_name("snipshot")
        iw, ih = scene.size
        self.set_default_size(max(1000, min(1500, iw + 140)), max(700, min(950, ih + 230)))
        self._status_timer = 0
        self._zoom_busy = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)
        self._build_actions()
        root.append(self._menubar())
        root.append(self._toolbar())
        self.props = PropBar(self.canvas, self)
        root.append(self.props)
        body = Gtk.Box()
        body.append(self._tools())
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        body.append(self.canvas)
        root.append(body)
        root.append(self._statusbar())

        c = self.canvas
        c.on_changed = self._changed
        c.on_selection = self._selection_changed
        c.on_status = self._set_coord
        c.on_zoom = self._zoom_changed
        c.on_size = self._size_changed
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        # Ctrl + wheel zooms. The scrolled window grabs wheel events before its children see them, so this is
        # caught one level up, in the capture phase, and only when the pointer is over the picture.
        wheel = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        wheel.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        wheel.connect("scroll", self._wheel)
        self.add_controller(wheel)
        self.connect("close-request", self._close_request)
        self._size_changed()
        self._changed()
        self.props.refresh()
        GLib.idle_add(self._initial_zoom)

    # ------------------------------------------------------------------ construction
    def _initial_zoom(self):
        if self.cfg.get("zoom_fit_on_open", True):
            self.canvas.zoom_fit()
        self.canvas.area.grab_focus()
        return False

    def _action(self, name, handler, accels=None, enabled=True):
        act = Gio.SimpleAction.new(name, None)
        act.connect("activate", lambda *_: handler())
        act.set_enabled(enabled)
        self.add_action(act)
        if accels:
            self.app.set_accels_for_action(f"win.{name}", accels)
        return act

    def _build_actions(self):
        A = self._action
        A("save", self.save, ["<Control>s"])
        A("save_as", self.save_as, ["<Control><Shift>s"])
        A("copy_image", lambda: self._text_or(self.copy_image, "copy-clipboard"), ["<Control>c"])       # the whole image, edits included
        A("print", self.print_image, ["<Control>p"])
        A("open_with", self.open_with)
        A("open_folder", self.open_folder)
        A("copy_path", self.copy_path)
        A("email", self.email)
        A("close", self.close, ["<Control>w", "<Alt>F4"])
        A("undo", lambda: self._text_or(lambda: self.canvas.undo(), "undo"), ["<Control>z"])
        A("redo", lambda: self._text_or(lambda: self.canvas.redo(), "redo"), ["<Control>y", "<Control><Shift>z"])
        A("cut", lambda: self._text_or(self.canvas.cut_selected, "cut-clipboard"), ["<Control>x"])
        A("copy", lambda: self._text_or(self._copy_objects, "copy-clipboard"), ["<Control><Shift>c"])    # just the selected objects
        A("paste", lambda: self._text_or(self.paste, "paste-clipboard"), ["<Control>v"])
        A("duplicate", self.canvas.duplicate_selected, ["<Control>d"])
        A("select_all", lambda: self._text_or(self.canvas.select_all, "select-all"), ["<Control>a"])
        A("delete", lambda: self._text_or(self.canvas.delete_selected, "delete-from-cursor"), ["Delete"])
        for how in ("front", "back", "up", "down"):
            A(f"arrange_{how}", lambda h=how: self.canvas.arrange(h),
              {"front": ["<Control><Shift>Page_Up"], "back": ["<Control><Shift>Page_Down"],
               "up": ["<Control>Page_Up"], "down": ["<Control>Page_Down"]}[how])
        for shape in ("arrow", "hand", "text", "crosshair", "busy"):
            A(f"cursor_{shape}", lambda s=shape: self.canvas.add_cursor(s))
        A("rotate_cw", lambda: self.canvas.rotate(True), ["<Control>period"])
        A("rotate_ccw", lambda: self.canvas.rotate(False), ["<Control>comma"])
        A("resize", self.dlg_resize)
        A("resize_canvas", self.dlg_canvas)
        A("auto_crop", self.canvas.crop_auto)
        A("border", self.dlg_border, ["<Control>b"])
        A("shadow", self.dlg_shadow, ["<Control>q"])
        A("torn", self.dlg_torn, ["<Control>t"])
        A("grayscale", lambda: self.canvas.apply_base_effect(im.grayscale), ["<Control>g"])
        A("invert", lambda: self.canvas.apply_base_effect(im.invert), ["<Control>i"])
        A("remove_alpha", lambda: self.canvas.apply_base_effect(im.remove_transparency))
        A("adjust", self.dlg_adjust)
        A("zoom_in", self.canvas.zoom_in, ["<Control>plus", "<Control>equal", "<Control>KP_Add"])
        A("zoom_out", self.canvas.zoom_out, ["<Control>minus", "<Control>KP_Subtract"])
        A("zoom_fit", self.canvas.zoom_fit, ["<Control>9"])
        A("zoom_actual", lambda: self.canvas.set_zoom(1.0), ["<Control>0"])
        A("preferences", lambda: self.app.show_preferences(self))
        A("about", lambda: DLG.about_dialog(self, CFG.VERSION))
        for tool, label in TOOL_LABELS:
            A(f"tool_{tool}", lambda t=tool: self.tool_buttons[t].set_active(True))

    def _menubar(self):
        def item(menu, label, action):
            menu.append(label, f"win.{action}")
        m = Gio.Menu()
        f = Gio.Menu()
        for lbl, a in (("Save", "save"), ("Save as...", "save_as"), ("Copy image to clipboard", "copy_image"),
                       ("Print...", "print"), ("E-mail...", "email")):
            item(f, lbl, a)
        f2 = Gio.Menu()
        for lbl, a in (("Open with default viewer", "open_with"), ("Open containing folder", "open_folder"),
                       ("Copy file path", "copy_path")):
            item(f2, lbl, a)
        f.append_section(None, f2)
        f3 = Gio.Menu()
        item(f3, "Close", "close")
        f.append_section(None, f3)
        m.append_submenu("_File", f)
        e = Gio.Menu()
        for lbl, a in (("Undo", "undo"), ("Redo", "redo")):
            item(e, lbl, a)
        e2 = Gio.Menu()
        for lbl, a in (("Cut", "cut"), ("Copy selected object", "copy"), ("Paste", "paste"), ("Duplicate", "duplicate"),
                       ("Select all", "select_all"), ("Delete", "delete")):
            item(e2, lbl, a)
        e.append_section(None, e2)
        m.append_submenu("_Edit", e)
        o = Gio.Menu()
        for tool, label in TOOL_LABELS[1:]:
            item(o, label.split(" (")[0], f"tool_{tool}")
        o1 = Gio.Menu()
        import cursors as _cur
        for shape, label in _cur.LABELS.items():
            o1.append(f"Mouse cursor: {label}", f"win.cursor_{shape}")
        o.append_section("Insert", o1)
        o2 = Gio.Menu()
        for lbl, a in (("Bring to front", "arrange_front"), ("Move up", "arrange_up"),
                       ("Move down", "arrange_down"), ("Send to back", "arrange_back")):
            item(o2, lbl, a)
        o.append_section("Arrange", o2)
        m.append_submenu("_Object", o)
        i = Gio.Menu()
        i1 = Gio.Menu()
        for lbl, a in (("Rotate clockwise", "rotate_cw"), ("Rotate counter-clockwise", "rotate_ccw"),
                       ("Resize...", "resize"), ("Resize canvas...", "resize_canvas"), ("Auto-crop", "auto_crop")):
            item(i1, lbl, a)
        i.append_section(None, i1)
        i2 = Gio.Menu()
        for lbl, a in (("Add border...", "border"), ("Drop shadow...", "shadow"), ("Torn edge...", "torn")):
            item(i2, lbl, a)
        i.append_section(None, i2)
        i3 = Gio.Menu()
        for lbl, a in (("Grayscale", "grayscale"), ("Invert", "invert"), ("Adjust colours...", "adjust"),
                       ("Remove transparency", "remove_alpha")):
            item(i3, lbl, a)
        i.append_section(None, i3)
        m.append_submenu("_Image", i)
        v = Gio.Menu()
        for lbl, a in (("Zoom in", "zoom_in"), ("Zoom out", "zoom_out"), ("Best fit", "zoom_fit"),
                       ("Actual size", "zoom_actual")):
            item(v, lbl, a)
        m.append_submenu("_View", v)
        h = Gio.Menu()
        item(h, "Preferences...", "preferences")
        item(h, "About Snipshot", "about")
        m.append_submenu("_Help", h)
        return Gtk.PopoverMenuBar.new_from_model(m)

    def _toolbar(self):
        bar = Gtk.Box(spacing=2)
        bar.add_css_class("topbar")
        bar.set_margin_start(6)
        bar.set_margin_end(6)
        bar.set_margin_top(3)
        bar.set_margin_bottom(3)

        def btn(icon, tip, action):
            b = Gtk.Button.new_from_icon_name(icon)
            b.set_tooltip_text(tip)
            b.set_action_name(f"win.{action}")
            b.add_css_class("flat")
            bar.append(b)
            return b

        def sep():
            bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4))
        btn("document-save-symbolic", "Save (Ctrl+S)", "save")
        btn("document-save-as-symbolic", "Save as... (Ctrl+Shift+S)", "save_as")
        btn("edit-copy-symbolic", "Copy image to clipboard (Ctrl+C)", "copy_image")
        btn("document-print-symbolic", "Print (Ctrl+P)", "print")
        btn("folder-open-symbolic", "Open containing folder", "open_folder")
        sep()
        btn("edit-cut-symbolic", "Cut object (Ctrl+X)", "cut")
        btn("edit-paste-symbolic", "Paste (Ctrl+V)", "paste")
        sep()
        btn("edit-undo-symbolic", "Undo (Ctrl+Z)", "undo")
        btn("edit-redo-symbolic", "Redo (Ctrl+Y)", "redo")
        sep()
        btn("edit-delete-symbolic", "Delete (Del)", "delete")
        sep()
        btn("object-rotate-left-symbolic", "Rotate counter-clockwise (Ctrl+,)", "rotate_ccw")
        btn("object-rotate-right-symbolic", "Rotate clockwise (Ctrl+.)", "rotate_cw")
        bar.append(Gtk.Box(hexpand=True))
        btn("preferences-system-symbolic", "Preferences", "preferences")
        return bar

    def _tools(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(4)
        box.set_margin_end(4)
        box.set_margin_top(4)
        self.tool_buttons = {}
        first = None
        for tool, tip in TOOL_LABELS:
            b = Gtk.ToggleButton()
            b.set_child(icons.tool_image(tool, 22))
            b.set_tooltip_text(tip)
            b.add_css_class("flat")
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._tool_toggled, tool)
            box.append(b)
            self.tool_buttons[tool] = b
        first.set_active(True)
        return box

    def _statusbar(self):
        bar = Gtk.Box(spacing=12)
        bar.add_css_class("statusbar")
        bar.set_margin_start(8)
        bar.set_margin_end(8)
        bar.set_margin_top(3)
        bar.set_margin_bottom(3)
        self.dims = Gtk.Label(label="", xalign=0)
        bar.append(self.dims)
        self.status = Gtk.Label(label="", xalign=0, hexpand=True, ellipsize=3)
        bar.append(self.status)
        self.coord = Gtk.Label(label="", xalign=1)
        self.coord.set_width_chars(12)
        bar.append(self.coord)
        self.zoom_dd = Gtk.DropDown.new_from_strings(ZOOM_ITEMS)
        self.zoom_dd.connect("notify::selected", self._zoom_picked)
        bar.append(self.zoom_dd)
        return bar

    # ------------------------------------------------------------------ canvas callbacks
    def _tool_toggled(self, button, tool):
        if button.get_active():
            self.canvas.set_tool(tool)
            self.props.refresh()

    def _selection_changed(self):
        self.props.refresh()
        self._refresh_actions()

    def _refresh_actions(self):
        c = self.canvas
        sel = bool(c.selection)
        for name, on in (("undo", c.can_undo()), ("redo", c.can_redo()), ("cut", sel), ("delete", sel),
                         ("duplicate", sel), ("arrange_front", sel), ("arrange_back", sel),
                         ("arrange_up", sel), ("arrange_down", sel)):
            act = self.lookup_action(name)
            if act:
                act.set_enabled(on)

    def _changed(self):
        name = os.path.basename(self.path) if self.path else (self.title_hint or "Untitled")
        self.set_title(f"{'* ' if self.canvas.modified else ''}{name} - Snipshot")
        self._refresh_actions()

    def _size_changed(self):
        w, h = self.canvas.scene.size
        self.dims.set_text(f"{w} x {h}")

    def _set_coord(self, text):
        self.coord.set_text(text)

    def say(self, text, seconds=7):
        self.status.set_text(text)
        if self._status_timer:
            GLib.source_remove(self._status_timer)
        self._status_timer = GLib.timeout_add_seconds(seconds, self._clear_status)

    def _clear_status(self):
        self.status.set_text("")
        self._status_timer = 0
        return False

    def _zoom_changed(self, z):
        self._zoom_busy = True
        label = f"{round(z * 100)}%"
        if self.canvas.fit:
            self.zoom_dd.set_selected(0)
        elif label in ZOOM_ITEMS:
            self.zoom_dd.set_selected(ZOOM_ITEMS.index(label))
        self._zoom_busy = False
        self.coord.set_tooltip_text(f"Zoom {label}")

    def _zoom_picked(self, *_):
        if self._zoom_busy:
            return
        i = self.zoom_dd.get_selected()
        if i == 0:
            self.canvas.zoom_fit()
        else:
            self.canvas.set_zoom(int(ZOOM_ITEMS[i].rstrip("%")) / 100)

    def _wheel(self, ctrl, dx, dy):
        if ctrl.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK and self.canvas.pointer_over():
            return self.canvas.handle_ctrl_scroll(dy)
        return False

    # ------------------------------------------------------------------ keyboard
    def _typing(self):
        f = self.get_focus()
        return isinstance(f, (Gtk.Text, Gtk.TextView, Gtk.Editable)) or self.canvas._edit is not None

    def _key(self, ctrl, keyval, keycode, state):
        if self._typing():
            return False
        mods = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.META_MASK)
        if mods:
            return False
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        name = Gdk.keyval_name(keyval) or ""
        c = self.canvas
        if keyval == Gdk.KEY_Escape:
            if c.crop is not None:
                self.cancel_crop()
            self.tool_buttons["select"].set_active(True)
            c.select([])
            return True
        if len(name) == 1 and name.lower() in TOOL_KEYS and not shift:
            tool = TOOL_KEYS[name.lower()]
            if tool == "crop" and c.tool == "crop":
                mode = ("default", "vertical", "horizontal")
                nxt = mode[(mode.index(c.defaults["crop"].get("mode", "default")) + 1) % 3]
                c.defaults["crop"]["mode"] = nxt
                if c.crop:
                    c.crop.p["mode"] = nxt
                self.props.refresh()
                c.area.queue_draw()
            else:
                self.tool_buttons[tool].set_active(True)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and c.crop is not None:
            self.confirm_crop()
            return True
        step = 10 if shift else 1
        moves = {Gdk.KEY_Left: (-step, 0), Gdk.KEY_Right: (step, 0), Gdk.KEY_Up: (0, -step), Gdk.KEY_Down: (0, step)}
        if keyval in moves and c.selection:
            c.nudge(*moves[keyval])
            return True
        return False

    def _text_or(self, fallback, widget_signal):
        """Edit actions go to the text box when you are typing in one, otherwise to the canvas."""
        f = self.get_focus()
        if isinstance(f, Gtk.TextView):
            if widget_signal == "undo":
                f.get_buffer().undo()
            elif widget_signal == "redo":
                f.get_buffer().redo()
            elif widget_signal == "delete-from-cursor":
                f.emit("delete-from-cursor", Gtk.DeleteType.CHARS, 1)
            else:
                f.emit(widget_signal)
            return
        if isinstance(f, Gtk.Text) and widget_signal in ("cut-clipboard", "copy-clipboard", "paste-clipboard", "select-all"):
            f.emit({"select-all": "select-all"}.get(widget_signal, widget_signal)) if widget_signal != "select-all" else f.select_region(0, -1)
            return
        fallback()

    # ------------------------------------------------------------------ crop
    def confirm_crop(self):
        if self.canvas.crop_confirm():
            self.tool_buttons["select"].set_active(True)
            self.say("Image cropped")

    def cancel_crop(self):
        self.canvas.crop_cancel()
        self.tool_buttons["select"].set_active(True)

    # ------------------------------------------------------------------ copy / paste
    def _copy_objects(self):
        if not self.canvas.copy_selected():
            self.copy_image()

    def paste(self):
        if self.canvas.paste_objects():
            return

        def got(arr):
            if arr is not None:
                self.canvas.add_image_object(arr)
                self.say("Pasted image from clipboard")
        output.read_clipboard_image(got)

    # ------------------------------------------------------------------ destinations
    def _arr(self):
        return self.canvas.export_array()

    def _error(self, text):
        d = Gtk.AlertDialog()
        d.set_message("Snipshot")
        d.set_detail(text)
        d.show(self)

    def save(self):
        try:
            path = self.path or CFG.next_save_path(self.cfg, title=self.title_hint)
            output.save_array(self._arr(), path, quality=self.cfg["jpg_quality"])
        except OSError as e:
            self._error(f"Could not save the image:\n{e}")
            return None
        self._saved(path)
        return path

    def _saved(self, path):
        self.path = path
        self.canvas.modified = False
        self.cfg.remember_file(path)
        self.cfg.save()
        self._changed()
        self.say(f"Saved to {path}")

    def save_as(self):
        dlg = Gtk.FileDialog(title="Save image as")
        base = os.path.basename(self.path) if self.path else os.path.basename(CFG.next_save_path(self.cfg, title=self.title_hint))
        dlg.set_initial_name(base)
        folder = os.path.dirname(self.path) if self.path else self.cfg.folder
        os.makedirs(folder, exist_ok=True)
        dlg.set_initial_folder(Gio.File.new_for_path(folder))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        for name, pats in (("PNG", ["*.png"]), ("JPEG", ["*.jpg", "*.jpeg"]), ("WebP", ["*.webp"]),
                           ("BMP", ["*.bmp"]), ("TIFF", ["*.tif", "*.tiff"])):
            f = Gtk.FileFilter()
            f.set_name(name)
            for p in pats:
                f.add_pattern(p)
            filters.append(f)
        dlg.set_filters(filters)

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            path = f.get_path()
            if not os.path.splitext(path)[1]:
                path += "." + self.cfg["format"]
            try:
                output.save_array(self._arr(), path, quality=self.cfg["jpg_quality"])
            except OSError as e:
                self._error(f"Could not save the image:\n{e}")
                return
            self._saved(path)
        dlg.save(self, None, done)

    def copy_image(self):
        output.copy_to_clipboard(self._arr())
        self.say("Image copied to clipboard")

    def print_image(self):
        output.print_array(self, self._arr(), os.path.basename(self.path or "Screenshot"))

    def _need_file(self):
        if self.path and os.path.exists(self.path):
            return self.path
        return self.save()

    def open_with(self):
        p = self._need_file()
        if p:
            output.open_path(p)

    def open_folder(self):
        p = self._need_file()
        if p:
            output.open_folder(p)

    def copy_path(self):
        p = self._need_file()
        if p:
            output.copy_text(p)
            self.say("Path copied to clipboard")

    def email(self):
        p = self._need_file()
        if p and not output.email_attachment(p):
            self._error("No mail program is configured (xdg-email is missing).")

    # ------------------------------------------------------------------ image effects
    def dlg_resize(self):
        w, h = self.canvas.scene.size
        DLG.resize_dialog(self, w, h, self.canvas.scale_to)

    def dlg_canvas(self):
        def ok(left, top, right, bottom, rgba):
            try:
                new = im.resize_canvas(self.canvas.scene.base, left, top, right, bottom, rgba)
            except ValueError as e:
                self._error(str(e))
                return
            self.canvas.apply_with_offset(new, left, top)
        DLG.canvas_dialog(self, ok)

    def dlg_border(self):
        def ok(width, rgba):
            self.canvas.apply_with_offset(im.add_border(self.canvas.scene.base, width, rgba), width, width)
        DLG.border_dialog(self, ok)

    def dlg_shadow(self):
        def ok(offset, blur, darkness):
            out, (ox, oy) = im.drop_shadow(self.canvas.scene.base, offset, darkness, blur, return_offset=True)
            self.canvas.apply_with_offset(out, ox, oy)
        DLG.shadow_dialog(self, ok)

    def dlg_torn(self):
        def ok(th, rng, edges, shadow):
            out, (ox, oy) = im.torn_edge(self.canvas.scene.base, th, rng, edges, shadow=shadow, return_offset=True)
            self.canvas.apply_with_offset(out, ox, oy)
        DLG.torn_dialog(self, ok)

    def dlg_adjust(self):
        sc = self.canvas.scene
        original = sc.base

        def preview(b, c, g):
            sc.base = im.adjust(original, b, c, g)
            sc.touch()
            self.canvas.area.queue_draw()

        def cancel():
            sc.base = original
            sc.touch()
            self.canvas.area.queue_draw()

        def ok(b, c, g):
            sc.base = original
            self.canvas.apply_base_effect(lambda base: im.adjust(base, b, c, g))
        DLG.adjust_dialog(self, preview, ok, cancel)

    # ------------------------------------------------------------------ closing
    def _close_request(self, *_):
        if self.canvas.modified and self.cfg.get("confirm_close_unsaved", True) and not getattr(self, "_closing_ok", False):
            self._ask_unsaved()
            return True
        self.app.editor_closed(self)
        return False

    def _ask_unsaved(self):
        d = Gtk.AlertDialog()
        d.set_message("Save the image before closing?")
        d.set_detail("The image has changes that have not been saved.")
        d.set_buttons(["Cancel", "Discard", "Save"])
        d.set_cancel_button(0)
        d.set_default_button(2)

        def done(dlg, res):
            try:
                choice = dlg.choose_finish(res)
            except GLib.Error:
                return
            if choice == 2 and not self.save():
                return
            if choice in (1, 2):
                self._closing_ok = True
                self.close()
        d.choose(self, None, done)
