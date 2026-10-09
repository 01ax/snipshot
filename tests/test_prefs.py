"""Preferences window: the Recording tab builds from the settings and writes them back (private headless session)."""
import atexit as _atexit, shutil as _shutil, tempfile as _tempfile
_made = []
def _mk(prefix="snipshot-"):
    d = _tempfile.mkdtemp(prefix=prefix); _made.append(d); return d
_atexit.register(lambda: [_shutil.rmtree(d, ignore_errors=True) for d in _made])
import os
import sys
import tempfile

os.environ["SNIPSHOT_CONFIG_DIR"] = _mk(prefix="snipshot-prefs-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402
import app as A
import config as CFG
import prefs as PR

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


class T(A.SnipshotApp):
    def apply_settings(self):
        self.applied = getattr(self, "applied", 0) + 1

    def activate_command(self, args):
        self.hold()
        cfg = self.cfg
        cfg["record_dir"] = "/tmp/vids"
        cfg["record_fps"] = 60
        cfg["record_quality"] = "high"
        win = PR.PrefsWindow(self)
        win.present()
        check("fps / quality / format show the saved settings", PR.FPS_CHOICES[win.rfps.get_selected()] == 60
              and PR.QUALITY_CHOICES[win.rquality.get_selected()][0] == "high" and win.rfmt.get_selected() == 0)
        check("folder shows the saved path", win.rfolder.get_text() == "/tmp/vids")
        check("the example file name is shown", win.rpreview.get_text().startswith("Example: Recording_") and win.rpreview.get_text().endswith(".mp4"), win.rpreview.get_text())
        win.rfolder.set_text("~/Videos/Mine")
        win.rpattern.set_text("Clip_${hh}-${mm}")
        win.rfmt.set_selected(1)
        win.rfps.set_selected(0)
        win.rquality.set_selected(2)
        win.rcount.set_value(5)
        win.rsys.set_active(False)
        win.rmic.set_active(True)
        win.rptr.set_active(False)
        check("the example follows the format and pattern", win.rpreview.get_text().startswith("Example: Clip_") and win.rpreview.get_text().endswith(".webm"), win.rpreview.get_text())
        check("the shortcuts section shows both shortcuts as not set", "Alt+Shift+G" in win.sc_label.get_text() and "Alt+Shift+R" in win.sc_label.get_text()
              and win.sc_label.get_text().count("not set yet") == 2, win.sc_label.get_text())
        win.sc_btn.emit("clicked")
        check("clicking the button sets them up (in the private session's own settings)", win.sc_label.get_text().count("set\n") + win.sc_label.get_text().count(": set") >= 2
              and "now runs" in win.sc_label.get_text(), win.sc_label.get_text())
        win._ok()
        c = CFG.Config(cfg.path)
        check("OK saves every recording setting", (c["record_dir"], c["record_name"], c["record_format"], c["record_fps"], c["record_quality"], c["record_countdown"],
                                                   c["record_system_audio"], c["record_mic"], c["record_cursor"])
              == ("~/Videos/Mine", "Clip_${hh}-${mm}", "webm", 15, "low", 5, False, True, False),
              str({k: c[k] for k in c if k.startswith("record_")}))
        check("the default output / microphone choice is 'default'", c["record_system_device"] == "" and c["record_mic_device"] == "")
        check("settings were re-applied", getattr(self, "applied", 0) >= 1)
        GLib.idle_add(self.quit)


T().run([])
print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
