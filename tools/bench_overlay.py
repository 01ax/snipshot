"""Overlay benchmark on synthetic frames (no screen capture involved)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SNIPSHOT_OVERLAY_BENCH"] = "1"
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
import numpy as np
import capture as CAP, screencast as SCN

class A(Gtk.Application):
    def do_activate(self):
        mons = SCN.list_monitors()
        rng = np.random.default_rng(1)
        shots = []
        for m in mons:
            arr = rng.integers(0, 255, (m.ph, m.pw, 4), dtype=np.uint8); arr[..., 3] = 255
            shots.append(SCN.MonitorShot(m, arr))
        sel = CAP.RegionSelector(shots, lambda r: self.quit(), True)
        sel.show()
        self.hold()
A(application_id="local.snipshot.bench").run([])
