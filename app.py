"""Snipshot application: command line, background daemon, capture flows, destinations, tray icon."""
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

import capture as CAP  # noqa: E402
import config as CFG  # noqa: E402
import editor as ED  # noqa: E402
import imaging as im  # noqa: E402
import model as M  # noqa: E402
import output  # noqa: E402
import icons as IC  # noqa: E402
import picker as PK  # noqa: E402
import prefs as PR  # noqa: E402
import recording as REC  # noqa: E402
import screencast as SCN  # noqa: E402
import tray as TR  # noqa: E402

APP_ID = CFG.APP_ID                       # "local.snipshot", or "local.snipshot.dev" for the side-by-side test copy
DEBUG = bool(os.environ.get("SNIPSHOT_DEBUG"))


def _log(*a):
    if DEBUG:
        print("[snipshot]", *a, file=sys.stderr, flush=True)


USAGE = """Snipshot - screenshot and screen recording tool

  snipshot region                capture a region (drag to select; the bar at the top switches to recording)
  snipshot record                the same overlay, opened in Record mode (run it again to stop a recording)
  snipshot record screen [NAME]  record a whole screen: left, right, a name like DP-2, or the primary one
  snipshot record window         record one window (the desktop's own picker)
  snipshot record stop           stop and save the running recording
  snipshot fullscreen [SCREEN]   capture the desktop: all (default), left, right, top, bottom or a name like DP-2
  snipshot window                capture a window (the desktop's own picker)
  snipshot lastregion            capture the previous region again
  snipshot clipboard             open the image on the clipboard in the editor
  snipshot FILE                  open an image file in the editor
  snipshot --daemon              start in the background with the tray icon
  snipshot prefs                 open preferences
  snipshot --quit                stop the background instance

  --delay SECONDS                wait before capturing (works with region, fullscreen, window, lastregion);
                                 for recordings it replaces the countdown before the recording starts
  --audio WHAT                   recordings: none, system, mic or system,mic (default: what you used last)
"""

CSS = """
window { font-size: 13px; }
.propbar { background: alpha(#000, .04); border-bottom: 1px solid alpha(#000, .12); }
.topbar { border-bottom: 1px solid alpha(#000, .10); }
.statusbar { border-top: 1px solid alpha(#000, .12); font-size: 12px; }
scale trough { min-height: 6px; background: #c5cbd4; border-radius: 3px; }
scale highlight { background: #1c71d8; border-radius: 3px; }
scale slider { background: #ffffff; border: 2px solid #1c71d8; }
scale value { font-size: 12px; font-weight: 600; }
.bold-btn label { font-weight: 800; }
.italic-btn label { font-style: italic; }
.countdown { font-size: 34px; font-weight: 700; }
.picker-thumb { border: 1px solid alpha(#000, .25); }
.snipshot-toolbar { background: rgba(16,17,22,.93); border-radius: 12px; padding: 6px 8px; color: #fff;
                    box-shadow: 0 6px 22px rgba(0,0,0,.5); }
.snipshot-toolbar button { color: #fff; background: transparent; border: none; border-radius: 8px; box-shadow: none;
                           padding: 6px 10px; min-height: 0; min-width: 0; text-shadow: none; }
.snipshot-toolbar button:hover { background: rgba(255,255,255,.14); }
.snipshot-toolbar button:checked { background: #1c71d8; }
.snipshot-toolbar button.rec:checked { background: #d62828; }
.snipshot-toolbar separator { background: rgba(255,255,255,.22); min-width: 1px; min-height: 22px; margin: 3px 6px; }
.snipshot-arm button.start { background: #d62828; font-weight: 700; padding: 6px 14px; }
.snipshot-arm button.start:hover { background: #ef4444; }
"""


class Countdown(Gtk.Window):
    """Small "Capturing in 3..." window. It is closed before the picture is taken, so it never appears in it."""

    def __init__(self, seconds, on_done, on_cancel, verb="Capturing"):
        super().__init__(title=CFG.DISPLAY_NAME, resizable=False)
        self.verb = verb
        self.left = max(1, int(round(seconds)))
        self.on_done, self.on_cancel, self.finished = on_done, on_cancel, False
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16, margin_bottom=16,
                      margin_start=26, margin_end=26)
        self.set_child(box)
        self.label = Gtk.Label(label="", css_classes=["countdown"])
        box.append(self.label)
        box.append(Gtk.Label(label="Get the screen ready - Esc cancels", css_classes=["dim-label"]))
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        box.append(cancel)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, k, *_: (self.close(), True)[1] if k == Gdk.KEY_Escape else False)
        self.add_controller(keys)
        self.connect("close-request", self._closing)
        self._show()
        self.timer = GLib.timeout_add_seconds(1, self._tick)

    def _show(self):
        self.label.set_text(f"{self.verb} in {self.left}...")

    def _tick(self):
        self.left -= 1
        if self.left <= 0:
            self.finished = True
            self.timer = 0
            self.close()
            GLib.timeout_add(220, lambda: (self.on_done(), False)[1])     # let the window disappear first
            return False
        self._show()
        return True

    def _closing(self, *_):
        if not self.finished:
            self.finished = True
            if self.timer:
                GLib.source_remove(self.timer)
            self.on_cancel()
        return False


class SnipshotApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = CFG.Config()
        self.editors = []
        self.tray = None
        self._held = False
        self._capturing = False
        self._hidden = []
        self._selector = None
        self._picker = None
        self.job = None                      # the RecordingJob while one is starting, running or stopping
        self._countdown = None
        self._countdown_secs = 0
        self._quit_when_saved = False

    # ------------------------------------------------------------------ lifecycle
    def do_startup(self):
        Gtk.Application.do_startup(self)
        st = Gtk.Settings.get_default()
        st.set_property("gtk-application-prefer-dark-theme", False)
        st.set_property("gtk-theme-name", "Adwaita")           # light and blue regardless of the desktop theme
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(os.path.join(self.data_dir(), "icons"))
        Gtk.Window.set_default_icon_name("snipshot")
        for name, handler in (("open-path", self._act_open_path), ("show-in-folder", self._act_show_in_folder)):
            act = Gio.SimpleAction.new(name, GLib.VariantType("s"))
            act.connect("activate", handler)
            self.add_action(act)
        self.apply_settings()

    @staticmethod
    def data_dir():
        """Where this copy keeps its icons. The normal install shares ~/.local/share; a dev copy keeps its own."""
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        return os.path.join(base, CFG.APP_NAME) if CFG.CHANNEL else base

    def launcher_path(self):
        return os.path.expanduser(f"~/.local/bin/{CFG.APP_NAME}")

    def _ensure_icons(self):
        """The tray needs the two icon files on disk (the app icon and the same icon with a red recording dot)."""
        folder = os.path.join(self.data_dir(), "icons", "hicolor", "scalable", "apps")
        try:
            os.makedirs(folder, exist_ok=True)
            for name, svg in (("snipshot.svg", IC.APP_ICON), ("snipshot-recording.svg", IC.RECORDING_ICON)):
                path = os.path.join(folder, name)
                try:
                    same = open(path, encoding="utf-8").read() == svg
                except OSError:
                    same = False
                if not same:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(svg)
        except OSError:
            pass

    def apply_settings(self):
        want_tray = self.cfg["show_tray_icon"]
        if self.tray is not None:
            self.tray.stop()
            self.tray = None
        if want_tray:
            self._ensure_icons()
            live = self.job is not None and self.job.state in ("recording", "stopping")
            self.tray = TR.TrayIcon(CFG.DISPLAY_NAME, "snipshot-recording" if live else "snipshot", self._tray_items(),
                                    icon_theme_path=os.path.join(self.data_dir(), "icons", "hicolor", "scalable", "apps"),
                                    on_activate=self._tray_clicked, app_id=CFG.APP_NAME)
            self.tray.start()
        if want_tray and not self._held:
            self.hold()
            self._held = True
        elif not want_tray and self._held:
            self.release()
            self._held = False

    def _screen_names(self):
        """[(label, argument)] for capturing a single screen, e.g. ('DP-2 (left)', 'DP-2')."""
        try:
            mons = SCN.list_monitors()
        except GLib.Error:
            return []
        if len(mons) < 2:
            return []
        out = []
        for m in mons:
            side = "left" if m is min(mons, key=lambda k: k.x) else ("right" if m is max(mons, key=lambda k: k.x) else "middle")
            out.append((f"{m.connector} ({side}, {m.pw}x{m.ph})", m.connector))
        return out

    def _tray_items(self):
        def it(label, cb):
            return {"label": label, "callback": cb}
        items = []
        if self.job is not None:                       # first entry while recording: the timer + stop (kept at index 0)
            items.append(it(self._stop_label(), self.stop_recording))
            items.append(None)
        items += [it("Capture region", self.capture_region), it("Capture last region", self.capture_last),
                  it("Capture window", self.capture_window), it("Capture full screen", self.capture_fullscreen)]
        for label, arg in self._screen_names():
            items.append(it(f"Capture screen {label}", lambda a=arg: self.capture_fullscreen(a)))
        items += [None, it("Capture region in 3 seconds", lambda: self.capture_region(delay=3)),
                  it("Capture region in 5 seconds", lambda: self.capture_region(delay=5)),
                  it("Capture full screen in 5 seconds", lambda: self.capture_fullscreen(delay=5)),
                  None]
        if self.job is None:
            items += [it("Record region or window...", lambda: self.record_command()),
                      it("Record full screen", lambda: self.record_command("screen")), None]
        items += [it("Open image from file...", self.open_dialog), it("Open image from clipboard", self.open_clipboard),
                  it("Open last capture location", self.open_last_location),
                  it("Open last recording", self.open_last_recording),
                  None, it("Preferences...", lambda: self.show_preferences()), it("Quit Snipshot", self.quit_all)]
        return items

    def _tray_clicked(self):
        if self.job is not None:
            self.stop_recording()                         # a click on the red recording icon means "stop"
        else:
            self.capture_region()

    def quit_all(self):
        if self.job is not None and not self._quit_when_saved:
            self._quit_when_saved = True                  # finish and save the recording first, then quit
            self.stop_recording()
            GLib.timeout_add_seconds(15, lambda: (self.quit_all(), False)[1])
            return
        for w in list(self.editors):
            w._closing_ok = True
            w.close()
        if self.tray:
            self.tray.stop()
        if self._held:
            self.release()
            self._held = False
        self.quit()

    # ------------------------------------------------------------------ command line
    def do_command_line(self, cmdline):
        self.activate_command(cmdline.get_arguments()[1:])
        return 0

    @staticmethod
    def parse_args(args):
        delay, _audio, rest = SnipshotApp.parse_opts(args)
        return delay, rest

    @staticmethod
    def parse_opts(args):
        """(delay seconds or None, audio set or None, remaining words). ``--audio none|system|mic|system,mic``."""
        delay, audio, rest, i = None, None, [], 0
        while i < len(args):
            a = args[i]
            if a == "--audio" and i + 1 < len(args) or a.startswith("--audio="):
                spec = args[i + 1] if a == "--audio" else a.split("=", 1)[1]
                audio = {w for w in spec.lower().replace("+", ",").split(",") if w in ("system", "mic")}
                i += 2 if a == "--audio" else 1
            elif a == "--delay" and i + 1 < len(args):
                try:
                    delay = max(0.0, float(args[i + 1]))
                except ValueError:
                    pass
                i += 2
            elif a.startswith("--delay="):
                try:
                    delay = max(0.0, float(a.split("=", 1)[1]))
                except ValueError:
                    pass
                i += 1
            else:
                rest.append(a)
                i += 1
        return delay, audio, rest

    def activate_command(self, args):
        delay, audio, rest = self.parse_opts(args)
        if not rest or rest == ["--daemon"]:
            if not rest and not self.editors:
                self.capture_region(delay=delay)         # no arguments: behave like Greenshot's launcher
            return
        cmd = rest[0]
        if cmd in ("-h", "--help", "help"):
            print(USAGE)
        elif cmd == "region":
            self.capture_region(delay=delay)
        elif cmd == "record":
            self.record_command(rest[1] if len(rest) > 1 else None, rest[2] if len(rest) > 2 else None, delay, audio)
        elif cmd == "fullscreen":
            self.capture_fullscreen(rest[1] if len(rest) > 1 else "all", delay=delay)
        elif cmd == "window":
            self.capture_window(delay=delay)
        elif cmd == "lastregion":
            self.capture_last(delay=delay)
        elif cmd == "clipboard":
            self.open_clipboard()
        elif cmd == "prefs":
            self.show_preferences()
        elif cmd in ("--quit", "quit", "exit"):
            self.quit_all()
        elif os.path.exists(cmd):
            self.open_file(cmd)
        else:
            print(f"snipshot: unknown command or missing file: {cmd}\n\n{USAGE}", file=sys.stderr)

    # ------------------------------------------------------------------ capture pipeline
    def _hide_editors(self):
        self._hidden = [w for w in self.editors if w.get_visible()]
        for w in self._hidden:
            w.set_visible(False)

    def _show_editors(self):
        for w in self._hidden:
            w.set_visible(True)
        self._hidden = []

    def _end_capture(self):
        self._capturing = False
        self._show_editors()

    def _run_capture(self, handler, delay=None):
        """Optional countdown, then hide our own windows, wait a beat for the compositor, then run ``handler``."""
        if self._capturing:
            return
        self._capturing = True
        secs = (self.cfg["capture_delay_ms"] / 1000.0) if delay is None else delay

        def go():
            self._hide_editors()
            GLib.timeout_add(300 if self._hidden else 60, lambda: (handler(), False)[1])
        if secs > 0:
            Countdown(secs, go, self._end_capture).present()
        else:
            go()

    def _grab(self, then):
        want_cursor = bool(self.cfg["capture_cursor"])
        _log("grabbing every monitor, cursor =", want_cursor)

        def done(shots, msg):
            _log("grab finished:", "ok" if shots else msg)
            then(shots, msg)
        CAP.grab(done, include_cursor=want_cursor)

    # -- region
    def capture_region(self, delay=None, mode="screenshot", rec_opts=None, rec_delay=None):
        """The selection overlay. ``mode`` is the tab it opens on ("screenshot" or "record"); the toolbar switches it."""
        shots_then = lambda shots, msg: self._region_shots(shots, msg, mode, rec_opts, rec_delay)      # noqa: E731
        self._run_capture(lambda: self._grab(shots_then), delay if mode == "screenshot" else 0)

    def _region_shots(self, shots, msg, mode="screenshot", rec_opts=None, rec_delay=None):
        if not shots:
            self._end_capture()
            self._notify(msg or "Capture failed")
            return
        rec = dict(system=bool(self.cfg["record_system_audio"]), mic=bool(self.cfg["record_mic"]),
                   cursor=bool(self.cfg["record_cursor"]))
        rec.update(rec_opts or {})
        self._selector = CAP.RegionSelector(shots, lambda r: self._region_done(r, rec_delay),
                                            bool(self.cfg["capture_cursor"]), mode=mode, rec=rec)
        self._selector.show()

    def _region_done(self, result, rec_delay=None):
        self._end_capture()
        self._selector = None
        if result is None:
            return
        if result["target"] == "window":
            if result["mode"] == "record":
                self.begin_recording({"kind": "window"}, result["opts"], rec_delay)
            else:
                self.capture_window()
            return
        if result["mode"] == "record":
            info = result["shot"].info
            target = {"kind": "monitor", "connector": info.connector, "size": (info.pw, info.ph),
                      "crop": result["region"] if result["target"] == "region" else None}
            self.begin_recording(target, result["opts"], rec_delay)
            return
        self.cfg["last_region"] = dict(monitor=result["monitor"], x=result["region"][0], y=result["region"][1],
                                       w=result["region"][2], h=result["region"][3])
        self.cfg.save()
        self.captured(result["array"], result["cursor"], "Region")

    # -- full screen
    def capture_fullscreen(self, which="all", delay=None):
        if not isinstance(which, str):
            which = "all"
        self._run_capture(lambda: self._grab(lambda shots, msg: self._fullscreen_shots(shots, msg, which)), delay)

    @staticmethod
    def pick_screens(shots, which):
        w = (which or "all").lower()
        if w == "left":
            return [min(shots, key=lambda s: s.info.x)]
        if w == "right":
            return [max(shots, key=lambda s: s.info.x)]
        if w == "top":
            return [min(shots, key=lambda s: s.info.y)]
        if w == "bottom":
            return [max(shots, key=lambda s: s.info.y)]
        if w.isdigit() and 1 <= int(w) <= len(shots):
            return [sorted(shots, key=lambda s: (s.info.x, s.info.y))[int(w) - 1]]
        named = [s for s in shots if s.info.connector.lower() == w]
        return named or list(shots)

    def _fullscreen_shots(self, shots, msg, which):
        self._end_capture()
        if not shots:
            self._notify(msg or "Capture failed")
            return
        chosen = self.pick_screens(shots, which)
        if len(chosen) == 1:
            arr, cursor = chosen[0].array, chosen[0].cursor
        else:
            arr, placed = SCN.combine(chosen)
            cursor = next(((s.cursor[0], s.cursor[1] + x, s.cursor[2] + y) for s, x, y in placed if s.cursor), None)
        self.captured(arr, cursor if self.cfg["capture_cursor"] else None, "Full screen")

    # -- window (the desktop's own picker; it plays its own shutter effects)
    def capture_window(self, delay=None):
        def handler():
            CAP.portal_screenshot(self._window_done, interactive=True)
        self._run_capture(handler, delay)

    def _window_done(self, arr, msg):
        self._end_capture()
        if arr is None:
            self._notify(msg or "Capture cancelled")
        else:
            self.captured(arr, None, "Window")

    # -- last region
    def capture_last(self, delay=None):
        last = self.cfg.get("last_region")
        if not isinstance(last, dict) or not last:
            return self.capture_region(delay=delay)
        self._run_capture(lambda: self._grab(lambda shots, msg: self._last_shots(shots, msg, last)), delay)

    def _last_shots(self, shots, msg, last):
        self._end_capture()
        if not shots:
            self._notify(msg or "Capture failed")
            return
        shot = next((s for s in shots if s.info.connector == last["monitor"]), None) or shots[0]
        h, w = shot.array.shape[:2]
        x, y = min(last["x"], w - 1), min(last["y"], h - 1)
        rw, rh = min(last["w"], w - x), min(last["h"], h - y)
        region = (x, y, rw, rh)
        cursor = CAP.cursor_in_region(shot, region) if self.cfg["capture_cursor"] else None
        self.captured(shot.array[y:y + rh, x:x + rw].copy(), cursor, "Region")

    # ------------------------------------------------------------------ screen recording
    def record_command(self, what=None, arg=None, delay=None, audio=None):
        """``snipshot record [stop | screen [NAME] | window]``. With nothing running it opens the overlay in Record mode;
        while a recording runs, any ``record`` command stops it (so the same shortcut starts and stops)."""
        if self.job is not None:
            return self.stop_recording()
        if what == "stop":
            return self._notify("Nothing is being recorded.")
        opts = None
        if audio is not None:
            opts = dict(system="system" in audio, mic="mic" in audio)
        if what in (None, "", "region"):
            return self.capture_region(mode="record", rec_opts=opts, rec_delay=delay)
        flags = dict(system=bool(self.cfg["record_system_audio"]), mic=bool(self.cfg["record_mic"]),
                     cursor=bool(self.cfg["record_cursor"]))
        flags.update(opts or {})
        if what == "window":
            return self.begin_recording({"kind": "window"}, flags, delay)
        if what == "screen":
            try:
                mons = SCN.list_monitors()
            except GLib.Error as e:
                return self._notify(f"Could not read the monitor layout: {e.message}")
            m = self.pick_monitor(mons, arg)
            if m is None:
                return self._notify("There is no screen to record.")
            return self.begin_recording({"kind": "monitor", "connector": m.connector, "size": (m.pw, m.ph), "crop": None},
                                        flags, delay)
        self._notify(f"Unknown recording command: {what}")

    @staticmethod
    def pick_monitor(mons, which=None):
        """left / right / top / bottom / a connector name like DP-2 / a number (1 = leftmost); default the primary screen."""
        if not mons:
            return None
        w = (which or "").lower()
        if w == "left":
            return min(mons, key=lambda m: m.x)
        if w == "right":
            return max(mons, key=lambda m: m.x)
        if w == "top":
            return min(mons, key=lambda m: m.y)
        if w == "bottom":
            return max(mons, key=lambda m: m.y)
        if w.isdigit() and 1 <= int(w) <= len(mons):
            return sorted(mons, key=lambda m: (m.x, m.y))[int(w) - 1]
        named = next((m for m in mons if m.connector.lower() == w), None)
        return named or next((m for m in mons if m.primary), mons[0])

    def begin_recording(self, target, opts, countdown=None):
        """Remember the sound/pointer choices for next time, open the source, count down, then start the file."""
        if self.job is not None:
            return
        for key, name in (("system", "record_system_audio"), ("mic", "record_mic"), ("cursor", "record_cursor")):
            self.cfg[name] = bool(opts.get(key, self.cfg[name]))
        self.cfg.save()
        self._countdown_secs = self.cfg["record_countdown"] if countdown is None else max(0.0, countdown)
        self.job = REC.RecordingJob(self.cfg, target, system=self.cfg["record_system_audio"], mic=self.cfg["record_mic"],
                                    cursor=self.cfg["record_cursor"], auto_begin=False, on_state=self._rec_state,
                                    on_tick=self._rec_tick, on_done=self._rec_done)
        self._refresh_tray()
        self.job.start()

    def stop_recording(self):
        if self.job is not None:
            self.job.stop()

    def _rec_state(self, state):
        _log("recording state:", state)
        job = self.job
        if job is None:
            return
        if state == "ready":                              # the source is open: count down, then begin
            if self._countdown_secs > 0:
                self._countdown = Countdown(self._countdown_secs, lambda: job.begin(), lambda: job.stop(), verb="Recording starts")
                self._countdown.present()
            else:
                GLib.timeout_add(120, lambda: (job.begin(), False)[1])
        elif state == "recording":
            self._refresh_tray()
        elif state == "stopping":
            if self.tray and self.tray.items and self.tray.items[0] and "Stop" in self.tray.items[0]["label"]:
                self.tray.set_item_label(0, "Saving the recording...")

    def _stop_label(self):
        t = REC.fmt_time(self.job.elapsed) if self.job is not None and self.job.state == "recording" else None
        return f"Stop recording ({t})" if t else "Cancel recording"

    def _rec_tick(self, seconds):
        if self.tray and self.job is not None and self.job.state == "recording":
            self.tray.set_item_label(0, self._stop_label())
            self.tray.set_tooltip(f"Recording {REC.fmt_time(seconds)} - click to stop")

    def _refresh_tray(self):
        if self.tray is None:
            return
        live = self.job is not None and self.job.state in ("recording", "stopping")      # red only once frames are being kept
        self.tray.set_icon("snipshot-recording" if live else "snipshot")
        self.tray.set_tooltip("Recording - click to stop" if live else "")
        self.tray.set_items(self._tray_items())

    def _rec_done(self, result):
        self.job = None
        self._countdown = None
        self._refresh_tray()
        _log("recording finished:", {k: v for k, v in result.items() if k != "notes"})
        extra = " ".join(result["notes"] + ([result["warning"]] if result["warning"] else []))
        if result["cancelled"]:
            pass
        elif result["error"] or not result["path"]:
            self._notify(f"Recording failed: {result['error'] or 'no file was written'}")
        else:
            self.cfg["last_recording"] = result["path"]
            self.cfg.save()
            self._notify(f"Recording saved: {os.path.basename(result['path'])} ({REC.fmt_time(result['seconds'])})"
                         + (f"\n{extra}" if extra else ""), path=result["path"], recording=True)
        if self._quit_when_saved:
            self.quit_all()

    def open_last_recording(self):
        p = self.cfg.get("last_recording") or ""
        if p and os.path.exists(p):
            self._act_open_path(None, GLib.Variant("s", p))
        else:
            folder = self.cfg.record_folder
            output.open_folder(folder if os.path.isdir(folder) else os.path.expanduser("~"))

    def _act_open_path(self, _action, param):
        path = param.get_string()
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
        except GLib.Error as e:
            self._notify(f"Could not open {path}: {e.message}")

    def _act_show_in_folder(self, _action, param):
        output.open_folder(param.get_string())

    # ------------------------------------------------------------------ destinations
    def captured(self, arr, cursor, title):
        _log("captured", title, f"{arr.shape[1]}x{arr.shape[0]}", "cursor" if cursor else "")
        dests = [d for d in self.cfg["after_capture"] if d in ("ask", "editor", "save", "clipboard")] or ["ask"]
        if "ask" in dests:
            self._show_picker(arr, cursor, title)
        else:
            for d in dests:
                self.run_destination(d, arr, cursor, title)

    def _show_picker(self, arr, cursor, title):
        shown = im.composite(arr, cursor[0], cursor[1], cursor[2]) if cursor else arr

        def chosen(key, result):
            if key is None:
                _log("discarded")
                self._picker = None
                return
            self.run_destination(key, arr, cursor, title, result)
        self._picker = PK.Picker(shown, chosen, f"{arr.shape[1]} x {arr.shape[0]}")
        self._picker.present()

    def run_destination(self, key, arr, cursor, title, done=lambda ok: None):
        """Carry out one destination. ``done(True)`` when finished, ``done(False)`` if it was cancelled or failed."""
        flat = lambda: im.composite(arr, cursor[0], cursor[1], cursor[2]) if cursor else arr      # noqa: E731
        if key == "editor":
            self.open_editor(arr, name=title, cursor=cursor, fresh=True)
            done(True)
        elif key == "clipboard":
            output.copy_to_clipboard(flat())
            self._notify("Image stored to clipboard.")
            done(True)
        elif key == "save":
            done(bool(self._save_flat(flat(), title)))
        elif key == "save_as":
            self._save_as(flat(), title, done)
        elif key == "print":
            output.print_array(None, flat(), title)
            done(True)
        elif key == "email":
            path = self._save_flat(flat(), title)
            if path and not output.email_attachment(path):
                self._notify("No mail program is configured (xdg-email is missing).")
            done(bool(path))
        else:
            done(False)

    def _save_flat(self, arr, title):
        try:
            path = output.save_array(arr, CFG.next_save_path(self.cfg, title=title), quality=self.cfg["jpg_quality"])
        except OSError as e:
            self._notify(f"Could not save: {e}")
            return None
        self.cfg.remember_file(path)
        self.cfg["last_saved"] = path
        self.cfg.save()
        self._notify(f"Image saved to {path}")
        return path

    def _save_as(self, arr, title, done):
        dlg = Gtk.FileDialog(title="Save image as")
        dlg.set_initial_name(os.path.basename(CFG.next_save_path(self.cfg, title=title)))
        os.makedirs(self.cfg.folder, exist_ok=True)
        dlg.set_initial_folder(Gio.File.new_for_path(self.cfg.folder))

        def finished(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                done(False)
                return
            path = f.get_path()
            if not os.path.splitext(path)[1]:
                path += "." + self.cfg["format"]
            try:
                output.save_array(arr, path, quality=self.cfg["jpg_quality"])
            except OSError as e:
                self._notify(f"Could not save: {e}")
                done(False)
                return
            self.cfg.remember_file(path)
            self.cfg["last_saved"] = path
            self.cfg.save()
            self._notify(f"Image saved to {path}")
            done(True)
        dlg.save(None, None, finished)

    def open_last_location(self):
        p = self.cfg.get("last_saved") or ""
        if p and os.path.exists(p):
            output.open_folder(p)
        else:
            output.open_folder(self.cfg.folder if os.path.isdir(self.cfg.folder) else os.path.expanduser("~"))

    # ------------------------------------------------------------------ opening images
    def open_editor(self, arr, name="", path=None, cursor=None, fresh=False):
        _log("opening editor", name, f"{arr.shape[1]}x{arr.shape[0]}")
        scene = M.Scene(arr)
        win = ED.EditorWindow(self, scene, self.cfg, name=name, path=path)
        if cursor:                                   # the captured mouse cursor is its own movable object
            win.canvas.add_cursor(sprite=cursor)
            win.canvas.undo_stack.clear()
            win.canvas.selection = []
        win.canvas.modified = bool(fresh)           # a fresh capture is unsaved, so closing it asks first
        win._changed()
        self.editors.append(win)
        win.present()
        return win

    def editor_closed(self, win):
        if win in self.editors:
            self.editors.remove(win)

    def open_file(self, path):
        try:
            arr = im.load_file(path)
        except Exception as e:                                   # noqa: BLE001
            self._notify(f"Could not open {path}: {e}")
            return
        self.open_editor(arr, name=os.path.basename(path), path=os.path.abspath(path))

    def open_dialog(self):
        dlg = Gtk.FileDialog(title="Open image")
        flt = Gtk.FileFilter()
        flt.set_name("Images")
        flt.add_mime_type("image/*")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(flt)
        dlg.set_filters(store)

        def done(d, res):
            try:
                self.open_file(d.open_finish(res).get_path())
            except GLib.Error:
                pass
        dlg.open(None, None, done)

    def open_clipboard(self):
        def got(arr):
            if arr is None:
                self._notify("There is no image on the clipboard")
            else:
                self.open_editor(arr, name="Clipboard")
        output.read_clipboard_image(got)

    def show_preferences(self, parent=None):
        PR.PrefsWindow(self, parent).present()

    def _notify(self, text, path=None, recording=False):
        """A desktop notification. With ``path`` the notification opens that file when clicked and offers "Show in
        folder". Recordings use a normal-priority notification so the banner (and its buttons) is really shown."""
        _log("notify:", text)
        if not self.cfg.get("show_notifications", True):
            return
        n = Gio.Notification.new(CFG.DISPLAY_NAME)
        n.set_body(text)
        n.set_icon(Gio.ThemedIcon.new("snipshot"))
        n.set_priority(Gio.NotificationPriority.NORMAL if recording else Gio.NotificationPriority.LOW)
        if path:
            n.set_default_action_and_target("app.open-path", GLib.Variant("s", path))
            n.add_button_with_target("Show in folder", "app.show-in-folder", GLib.Variant("s", path))
        self.send_notification(None, n)


def _instance_running():
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        r = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                          GLib.Variant("(s)", (APP_ID,)), None, Gio.DBusCallFlags.NONE, 2000, None)
        return bool(r.unpack()[0])
    except GLib.Error:
        return False


def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help", "help"):
        print(USAGE)                                  # never start the app just to print help
        return 0
    if args and args[0] in ("--quit", "quit", "exit") and not _instance_running():
        print("Snipshot is not running.")
        return 0
    app = SnipshotApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
