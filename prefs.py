"""Preferences window (Greenshot-style tabs: General, Capture, Output, Obfuscate)."""
import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

import config as CFG  # noqa: E402
import recorder as R  # noqa: E402
import shortcuts as SH  # noqa: E402

AUTOSTART = os.path.expanduser(f"~/.config/autostart/{CFG.APP_NAME}.desktop")
FPS_CHOICES = (15, 24, 30, 60)
QUALITY_CHOICES = (("high", "High (large files)"), ("medium", "Medium"), ("low", "Low (small files)"))


def set_autostart(enabled, exe):
    if enabled:
        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        with open(AUTOSTART, "w", encoding="utf-8") as fh:
            fh.write(f"[Desktop Entry]\nType=Application\nName={CFG.DISPLAY_NAME}\nComment=Screenshot tool (tray icon)\n"
                     f"Exec={exe} --daemon\nIcon=snipshot\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")
    elif os.path.exists(AUTOSTART):
        os.remove(AUTOSTART)


class PrefsWindow(Gtk.Window):
    def __init__(self, app, parent=None):
        super().__init__(title="Snipshot preferences", transient_for=parent, modal=False, destroy_with_parent=True)
        self.app, self.cfg = app, app.cfg
        self.set_default_size(560, -1)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12, margin_bottom=12,
                        margin_start=14, margin_end=14)
        self.set_child(outer)
        nb = Gtk.Notebook()
        outer.append(nb)
        nb.append_page(self._general(), Gtk.Label(label="General"))
        nb.append_page(self._capture(), Gtk.Label(label="Capture"))
        nb.append_page(self._output(), Gtk.Label(label="Output"))
        nb.append_page(self._recording(), Gtk.Label(label="Recording"))
        nb.append_page(self._obfuscate(), Gtk.Label(label="Obfuscate"))
        row = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        ok = Gtk.Button(label="OK")
        ok.add_css_class("suggested-action")
        ok.connect("clicked", lambda *_: self._ok())
        row.append(cancel)
        row.append(ok)
        outer.append(row)

    @staticmethod
    def _page():
        return Gtk.Grid(column_spacing=12, row_spacing=10, margin_top=14, margin_bottom=14, margin_start=14,
                        margin_end=14)

    @staticmethod
    def _row(grid, r, label, widget):
        grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
        widget.set_hexpand(True)
        grid.attach(widget, 1, r, 1, 1)
        return widget

    def _general(self):
        g = self._page()
        self.tray = Gtk.CheckButton(label="Show the tray icon and keep running in the background")
        self.tray.set_active(self.cfg["show_tray_icon"])
        g.attach(self.tray, 0, 0, 2, 1)
        self.autostart = Gtk.CheckButton(label="Start Snipshot when I log in")
        self.autostart.set_active(os.path.exists(AUTOSTART))
        g.attach(self.autostart, 0, 1, 2, 1)
        self.confirm = Gtk.CheckButton(label="Ask before closing an image with unsaved changes")
        self.confirm.set_active(self.cfg["confirm_close_unsaved"])
        g.attach(self.confirm, 0, 2, 2, 1)
        self.fit = Gtk.CheckButton(label="Fit large images to the editor window when opening")
        self.fit.set_active(self.cfg["zoom_fit_on_open"])
        g.attach(self.fit, 0, 3, 2, 1)
        g.attach(Gtk.Label(label="Keyboard shortcuts (GNOME)", xalign=0, margin_top=10), 0, 4, 2, 1)
        self.sc_label = Gtk.Label(xalign=0, wrap=True)
        self.sc_label.add_css_class("dim-label")
        g.attach(self.sc_label, 0, 5, 2, 1)
        self.sc_btn = Gtk.Button(label="Set up the shortcuts", halign=Gtk.Align.START)
        self.sc_btn.connect("clicked", lambda *_: self._set_shortcuts())
        g.attach(self.sc_btn, 0, 6, 2, 1)
        self._refresh_shortcuts()
        return g

    def _refresh_shortcuts(self, extra=""):
        names = {"ok": "set", "missing": "not set yet", "different": "set to other keys", "conflict": "keys used by another shortcut"}
        try:
            rows = SH.status()
        except GLib.Error:
            self.sc_label.set_text("This needs the GNOME desktop; set the shortcuts in your desktop's keyboard settings instead.")
            self.sc_btn.set_sensitive(False)
            return
        lines = []
        for w, state, _e in rows:
            keys = w["binding"].replace("<Alt>", "Alt+").replace("<Shift>", "Shift+")
            lines.append(f"{keys[:-1]}{keys[-1].upper()}  -  {'capture a screenshot' if w['arg'] == 'region' else 'record the screen'}: {names[state]}")
        self.sc_label.set_text("\n".join(lines) + (f"\n\n{extra}" if extra else ""))

    def _set_shortcuts(self):
        """Only runs when this button is clicked. Another program's shortcut is never replaced."""
        try:
            self._refresh_shortcuts(SH.describe(SH.apply()))
        except GLib.Error as e:
            self._refresh_shortcuts(f"Could not change the shortcuts: {e.message}")

    def _capture(self):
        g = self._page()
        g.attach(Gtk.Label(label="After capturing:", xalign=0), 0, 0, 2, 1)
        dests = self.cfg["after_capture"]
        self.ask = Gtk.CheckButton(label="Ask me what to do (destination menu, like Greenshot)")
        self.fixed = Gtk.CheckButton(label="Always do the following:")
        self.fixed.set_group(self.ask)
        (self.ask if "ask" in dests or not dests else self.fixed).set_active(True)
        g.attach(self.ask, 0, 1, 2, 1)
        g.attach(self.fixed, 0, 2, 2, 1)
        self.after = {}
        for i, (key, text) in enumerate((("editor", "Open in the image editor"), ("save", "Save to the output folder"),
                                         ("clipboard", "Copy to the clipboard"))):
            c = Gtk.CheckButton(label=text)
            c.set_margin_start(24)
            c.set_active(key in dests)
            g.attach(c, 0, i + 3, 2, 1)
            self.after[key] = c
        self.cursor = Gtk.CheckButton(label="Capture the mouse pointer (as a movable object in the editor)")
        self.cursor.set_active(self.cfg["capture_cursor"])
        g.attach(self.cursor, 0, 6, 2, 1)
        self.notify = Gtk.CheckButton(label="Show a notification after saving or copying")
        self.notify.set_active(self.cfg["show_notifications"])
        g.attach(self.notify, 0, 7, 2, 1)
        self.delay = self._row(g, 8, "Capture delay (ms)", Gtk.SpinButton.new_with_range(0, 30000, 100))
        self.delay.set_value(self.cfg["capture_delay_ms"])
        hint = Gtk.Label(label="The delay applies to every capture. For a one-off delay use the tray menu "
                               "(Capture ... in 3/5 seconds) or: snipshot --delay 5 region",
                         xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        g.attach(hint, 0, 9, 2, 1)
        return g

    def _output(self):
        g = self._page()
        self.folder = self._row(g, 0, "Output folder", Gtk.Entry(text=self.cfg["output_dir"]))
        pick = Gtk.Button(label="Choose...")
        pick.connect("clicked", lambda *_: self._pick_folder())
        g.attach(pick, 2, 0, 1, 1)
        self.pattern = self._row(g, 1, "File name pattern", Gtk.Entry(text=self.cfg["filename_pattern"]))
        self.preview = Gtk.Label(xalign=0)
        self.preview.add_css_class("dim-label")
        g.attach(self.preview, 1, 2, 2, 1)
        self.pattern.connect("changed", lambda *_: self._update_preview())
        self.fmt = self._row(g, 3, "Image format", Gtk.DropDown.new_from_strings([f.upper() for f in CFG.FORMATS]))
        self.fmt.set_selected(CFG.FORMATS.index(self.cfg["format"]))
        self.fmt.connect("notify::selected", lambda *_: self._update_preview())
        self.quality = self._row(g, 4, "JPEG / WebP quality", Gtk.SpinButton.new_with_range(1, 100, 1))
        self.quality.set_value(self.cfg["jpg_quality"])
        hint = Gtk.Label(label="Variables: ${YYYY} ${MM} ${DD} ${hh} ${mm} ${ss} ${title} ${hostname} ${username} ${NUM}",
                         xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        g.attach(hint, 0, 5, 3, 1)
        self._update_preview()
        return g

    def _recording(self):
        g = self._page()
        self.rfolder = self._row(g, 0, "Recordings folder", Gtk.Entry(text=self.cfg["record_dir"]))
        pick = Gtk.Button(label="Choose...")
        pick.connect("clicked", lambda *_: self._pick_folder(self.rfolder, "Recordings folder"))
        g.attach(pick, 2, 0, 1, 1)
        self.rpattern = self._row(g, 1, "File name pattern", Gtk.Entry(text=self.cfg["record_name"]))
        self.rpreview = Gtk.Label(xalign=0)
        self.rpreview.add_css_class("dim-label")
        g.attach(self.rpreview, 1, 2, 2, 1)
        avail = R.encoders_available()
        labels = [R.FORMATS[f]["label"] + ("" if avail.get(f) else " - not installed") for f in CFG.RECORD_FORMATS]
        self.rfmt = self._row(g, 3, "Video format", Gtk.DropDown.new_from_strings(labels))
        self.rfmt.set_selected(CFG.RECORD_FORMATS.index(self.cfg["record_format"]))
        self.rfmt.connect("notify::selected", lambda *_: self._update_rpreview())
        self.rfps = self._row(g, 4, "Frame rate", Gtk.DropDown.new_from_strings([f"{f} frames per second" for f in FPS_CHOICES]))
        fps = int(self.cfg["record_fps"])
        self.rfps.set_selected(FPS_CHOICES.index(fps) if fps in FPS_CHOICES else FPS_CHOICES.index(30))
        self.rquality = self._row(g, 5, "Quality", Gtk.DropDown.new_from_strings([t for _k, t in QUALITY_CHOICES]))
        self.rquality.set_selected([k for k, _t in QUALITY_CHOICES].index(self.cfg["record_quality"]))
        self.rcount = self._row(g, 6, "Countdown (seconds)", Gtk.SpinButton.new_with_range(0, 10, 1))
        self.rcount.set_value(self.cfg["record_countdown"])
        g.attach(Gtk.Label(label="Start with these switched on:", xalign=0), 0, 7, 3, 1)
        self.rsys = Gtk.CheckButton(label="System sound (what the computer plays)")
        self.rsys.set_active(self.cfg["record_system_audio"])
        self.rmic = Gtk.CheckButton(label="Microphone")
        self.rmic.set_active(self.cfg["record_mic"])
        self.rptr = Gtk.CheckButton(label="Mouse pointer")
        self.rptr.set_active(self.cfg["record_cursor"])
        for i, w in enumerate((self.rsys, self.rmic, self.rptr)):
            w.set_margin_start(24)
            g.attach(w, 0, 8 + i, 3, 1)
        self.rawake = Gtk.CheckButton(label="Keep the screen awake while recording (no automatic screen-off or lock)")
        self.rawake.set_active(self.cfg["record_keep_awake"])
        g.attach(self.rawake, 0, 14, 3, 1)
        try:
            devs = R.list_audio_devices()
        except GLib.Error:
            devs = {"inputs": [], "outputs": []}
        self._out_nodes = [""] + [n for _l, n, _d in devs["outputs"]]
        self._in_nodes = [""] + [n for _l, n, _d in devs["inputs"]]
        self.rout = self._row(g, 11, "Sound output to record",
                              Gtk.DropDown.new_from_strings(["Default output"] + [l for l, _n, _d in devs["outputs"]]))
        self.rin = self._row(g, 12, "Microphone",
                             Gtk.DropDown.new_from_strings(["Default microphone"] + [l for l, _n, _d in devs["inputs"]]))
        want_out, want_in = self.cfg["record_system_device"], self.cfg["record_mic_device"]
        self.rout.set_selected(self._out_nodes.index(want_out) if want_out in self._out_nodes else 0)
        self.rin.set_selected(self._in_nodes.index(want_in) if want_in in self._in_nodes else 0)
        hint = Gtk.Label(label="Press R in the capture overlay (Alt+Shift+G), or run: snipshot record. Run it again, or "
                               "click the red tray icon, to stop. Variables: ${YYYY} ${MM} ${DD} ${hh} ${mm} ${ss}.",
                         xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        g.attach(hint, 0, 13, 3, 1)
        self.rpattern.connect("changed", lambda *_: self._update_rpreview())
        self._update_rpreview()
        return g

    def _update_rpreview(self):
        fmt = CFG.RECORD_FORMATS[self.rfmt.get_selected()]
        self.rpreview.set_text("Example: " + CFG.expand_pattern(self.rpattern.get_text()) + "." + fmt)

    def _obfuscate(self):
        g = self._page()
        g.attach(Gtk.Label(label="Starting values for the Obfuscate tool (you can still change them per object):",
                           xalign=0, wrap=True), 0, 0, 2, 1)
        self.px = self._row(g, 1, "Pixel size", Gtk.SpinButton.new_with_range(2, 100, 1))
        self.px.set_value(self.cfg["obfuscate_pixel_size"])
        self.bl = self._row(g, 2, "Blur radius", Gtk.SpinButton.new_with_range(1, 100, 1))
        self.bl.set_value(self.cfg["obfuscate_blur_radius"])
        self.rand = Gtk.CheckButton(label="Randomise pixelation blocks (harder to reverse, less tidy)")
        self.rand.set_active(self.cfg["obfuscate_randomise"])
        g.attach(self.rand, 0, 3, 2, 1)
        note = Gtk.Label(label="Tip: pixelating or blurring text only hides it from casual viewing. For passwords or "
                               "keys, cover them with a solid filled rectangle instead.", xalign=0, wrap=True)
        note.add_css_class("dim-label")
        g.attach(note, 0, 4, 2, 1)
        return g

    def _update_preview(self):
        fmt = CFG.FORMATS[self.fmt.get_selected()]
        self.preview.set_text("Example: " + CFG.expand_pattern(self.pattern.get_text()) + "." + fmt)

    def _pick_folder(self, entry=None, title="Output folder"):
        entry = entry or self.folder
        dlg = Gtk.FileDialog(title=title)
        dlg.set_initial_folder(Gio.File.new_for_path(os.path.expanduser(entry.get_text())))

        def done(d, res):
            try:
                entry.set_text(d.select_folder_finish(res).get_path())
            except GLib.Error:
                pass
        dlg.select_folder(self, None, done)

    def _ok(self):
        c = self.cfg
        c["show_tray_icon"] = self.tray.get_active()
        c["confirm_close_unsaved"] = self.confirm.get_active()
        c["zoom_fit_on_open"] = self.fit.get_active()
        c["after_capture"] = ["ask"] if self.ask.get_active() else ([k for k, w in self.after.items() if w.get_active()] or ["ask"])
        c["capture_cursor"] = self.cursor.get_active()
        c["show_notifications"] = self.notify.get_active()
        c["capture_delay_ms"] = int(self.delay.get_value())
        c["output_dir"] = self.folder.get_text().strip() or CFG.DEFAULTS["output_dir"]
        c["filename_pattern"] = self.pattern.get_text().strip() or CFG.DEFAULTS["filename_pattern"]
        c["format"] = CFG.FORMATS[self.fmt.get_selected()]
        c["jpg_quality"] = int(self.quality.get_value())
        c["obfuscate_pixel_size"] = int(self.px.get_value())
        c["obfuscate_blur_radius"] = int(self.bl.get_value())
        c["obfuscate_randomise"] = self.rand.get_active()
        c["record_dir"] = self.rfolder.get_text().strip() or CFG.DEFAULTS["record_dir"]
        c["record_name"] = self.rpattern.get_text().strip() or CFG.DEFAULTS["record_name"]
        c["record_format"] = CFG.RECORD_FORMATS[self.rfmt.get_selected()]
        c["record_fps"] = FPS_CHOICES[self.rfps.get_selected()]
        c["record_quality"] = QUALITY_CHOICES[self.rquality.get_selected()][0]
        c["record_countdown"] = int(self.rcount.get_value())
        c["record_system_audio"] = self.rsys.get_active()
        c["record_mic"] = self.rmic.get_active()
        c["record_cursor"] = self.rptr.get_active()
        c["record_keep_awake"] = self.rawake.get_active()
        c["record_system_device"] = self._out_nodes[self.rout.get_selected()]
        c["record_mic_device"] = self._in_nodes[self.rin.get_selected()]
        c["autostart"] = self.autostart.get_active()
        c.save()
        try:
            set_autostart(c["autostart"], self.app.launcher_path())
        except OSError:
            pass
        self.app.apply_settings()
        self.close()
