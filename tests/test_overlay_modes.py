"""The selection overlay's Screenshot | Record toolbar, driven with real (synthetic) mouse and key events inside the
PRIVATE headless session:

    tools/headless_session.sh python3 -I tests/test_overlay_modes.py [screenshots-dir]
"""
import os
import subprocess
import sys
import threading
import time

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("Refusing to run: start this with tools/headless_session.sh.")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402
import app as A
import capture as CAP
import screencast
import remote_input

SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


class Driver:
    """Runs ``script`` in a worker thread (it sleeps while events arrive) and lets it touch GTK safely."""

    def __init__(self):
        self.app = Gtk.Application(application_id="local.snipshot.overlaytest")
        self.app.connect("activate", self._activate)
        self.sel = None
        self.done = []

    def on_main(self, fn, *args):
        ev, box = threading.Event(), []

        def run():
            try:
                box.append(fn(*args))
            except Exception as e:                            # noqa: BLE001
                box.append(e)
            ev.set()
            return False
        GLib.idle_add(run)
        ev.wait(15)
        if box and isinstance(box[0], Exception):
            raise box[0]
        return box[0] if box else None

    def _activate(self, app):
        app.hold()
        st = Gtk.Settings.get_default()
        st.set_property("gtk-theme-name", "Adwaita")
        prov = Gtk.CssProvider()
        prov.load_string(A.CSS) if hasattr(prov, "load_string") else prov.load_from_string(A.CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            script(self)
        except Exception as e:                                # noqa: BLE001
            import traceback
            traceback.print_exc()
            check("script ran to the end", False, repr(e))
        GLib.idle_add(self.app.quit)

    # ---- helpers for the script
    def open_overlay(self, mode):
        self.done.clear()
        info = screencast.list_monitors()[0]
        arr = np.zeros((info.ph, info.pw, 4), np.uint8)
        arr[..., 0] = np.linspace(40, 200, info.pw, dtype=np.uint8)[None, :]
        arr[..., 1] = np.linspace(60, 160, info.ph, dtype=np.uint8)[:, None]
        arr[..., 2] = 120
        arr[..., 3] = 255
        shot = screencast.MonitorShot(info, arr, None)

        def make():
            self.sel = CAP.RegionSelector([shot], lambda r: self.done.append(r), True, mode=mode,
                                          rec=dict(system=True, mic=False, cursor=True))
            self.sel.show()
        self.on_main(make)
        time.sleep(1.5)
        self.inp.move(640, 380)                              # the first pointer events only make the new window "entered"
        self.inp.move(650, 390)

    def centre(self, widget):
        def f():
            win = self.sel.shared.windows[0]
            ok, rect = widget.compute_bounds(win)
            return rect.get_x() + rect.get_width() / 2, rect.get_y() + rect.get_height() / 2
        return self.on_main(f)

    def tb(self, name):
        return getattr(self.sel.shared.windows[0].toolbar, name)

    def click_widget(self, inp, widget):
        x, y = self.centre(widget)
        inp.click(x, y)

    def shot(self, name):
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "grab_png.py"), os.path.join(SHOTS, name)],
                           timeout=30, check=False)


def script(d):
    inp = d.inp = remote_input.RemoteInput()
    time.sleep(0.5)
    tb = lambda n: getattr(d.sel.shared.windows[0].toolbar, n)           # noqa: E731
    vis = lambda w: d.on_main(w.get_visible)                              # noqa: E731

    # ---- screenshot mode
    d.open_overlay("screenshot")
    check("opens in screenshot mode", d.sel.mode == "screenshot")
    check("screenshot mode hides the audio switches", not vis(tb("b_sys")) and not vis(tb("b_mic")))
    check("Screenshot button is the active one", d.on_main(tb("b_shot").get_active) and not d.on_main(tb("b_rec").get_active))
    d.shot("overlay-screenshot")
    inp.drag((300, 200), (700, 450))
    check("screenshot: a drag finishes at once", len(d.done) == 1 and d.done[0]["mode"] == "screenshot" and d.done[0]["target"] == "region", str(d.done and d.done[0]["region"]))
    r = d.done[0]
    check("screenshot: real pixels of the dragged area", r["array"].shape[:2] == (250, 400) and abs(r["region"][0] - 300) <= 1, str(r["region"]))

    # ---- switch to record with the button, set the options
    d.open_overlay("screenshot")
    d.click_widget(inp, tb("b_rec"))
    check("clicking Record switches mode", d.sel.mode == "record")
    check("record mode shows system sound + microphone", vis(tb("b_sys")) and vis(tb("b_mic")))
    check("defaults: system sound on, microphone off", d.sel.rec["system"] and not d.sel.rec["mic"])
    d.click_widget(inp, tb("b_mic"))
    check("clicking Microphone turns it on", d.sel.rec["mic"] is True and d.on_main(tb("b_mic").get_active))
    d.click_widget(inp, tb("b_sys"))
    check("clicking System sound turns it off", d.sel.rec["system"] is False and not d.on_main(tb("b_sys").get_active))
    inp.key("v")
    check("V key toggles the microphone", d.sel.rec["mic"] is False)
    inp.key("a")
    check("A key toggles system sound", d.sel.rec["system"] is True)
    shot_cursor = d.sel.include_cursor
    d.click_widget(inp, tb("b_ptr"))
    check("pointer switch changes the recording's flag only", d.sel.rec["cursor"] is False and d.sel.include_cursor == shot_cursor)
    inp.key("m")
    check("M key toggles the pointer", d.sel.rec["cursor"] is True)

    # ---- record: drag arms, Enter starts
    inp.drag((300, 200), (700, 450))
    check("record: a drag does NOT finish, it waits for Start", d.done == [] and d.sel.shared.armed)
    check("record: Start / Cancel buttons appear", vis(d.sel.shared.windows[0].arm_bar))
    d.shot("overlay-armed")
    inp.key("Return")
    r = d.done[0] if d.done else None
    check("record: Enter hands back a recording of that region", r and r["mode"] == "record" and r["target"] == "region"
          and r["region"][2:] == (400, 250), str(r and (r["target"], r["region"])))
    check("record: options come back with the result", r and r["opts"] == dict(system=True, mic=False, cursor=True), str(r and r["opts"]))

    # ---- accidental tiny drag, redo, Start button
    d.open_overlay("record")
    inp.drag((500, 300), (504, 303))
    check("record: a tiny accidental drag is ignored (overlay stays)", d.done == [] and not d.sel.shared.armed)
    inp.drag((100, 100), (300, 250))
    inp.drag((200, 150), (800, 500))
    check("record: dragging again replaces the area", d.sel.shared.armed and d.sel.shared.rect()[2:] == (600, 350), str(d.sel.shared.rect()))
    d.click_widget(inp, d.sel.shared.windows[0].arm_bar.get_first_child())
    check("record: the red Start button starts the recording", len(d.done) == 1 and d.done[0]["region"][2:] == (600, 350), str(d.done and d.done[0]["region"]))

    # ---- switching mode drops the chosen area
    d.open_overlay("record")
    inp.drag((100, 100), (300, 250))
    inp.key("s")
    check("switching to Screenshot clears the chosen area", d.sel.mode == "screenshot" and not d.sel.shared.armed
          and not vis(d.sel.shared.windows[0].arm_bar))
    inp.key("Escape")
    check("Esc cancels", d.done == [None])

    # ---- This screen / Window...
    d.open_overlay("record")
    d.click_widget(inp, tb("b_screen"))
    r = d.done[0] if d.done else None
    check("This screen records the whole monitor", r and r["mode"] == "record" and r["target"] == "screen" and r["region"] == (0, 0, 1280, 720), str(r and r["region"]))
    d.open_overlay("record")
    d.click_widget(inp, tb("b_window"))
    r = d.done[0] if d.done else None
    check("Window... asks for a window recording", r and r["mode"] == "record" and r["target"] == "window")
    d.open_overlay("screenshot")
    d.click_widget(inp, tb("b_window"))
    r = d.done[0] if d.done else None
    check("Window... in screenshot mode asks for a window screenshot", r and r["mode"] == "screenshot" and r["target"] == "window")
    d.open_overlay("record")
    inp.key("Return")
    r = d.done[0] if d.done else None
    check("record: Enter with nothing chosen records the whole screen", r and r["target"] == "screen")
    d.open_overlay("screenshot")
    inp.key("r")
    check("R key switches to record", d.sel.mode == "record")
    d.shot("overlay-record")
    inp.key("Escape")
    inp.close()


Driver().app.run([])
print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
