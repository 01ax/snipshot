import os, sys, tempfile
os.environ["SNIPSHOT_CONFIG_DIR"] = tempfile.mkdtemp(prefix="snipshot-ui-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
import numpy as np
import app as A, capture as CAP, dialogs as DLG, imaging as im, model as M

OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)

def snap(win, name):
    w, h = win.get_width(), win.get_height()
    sn = Gtk.Snapshot(); Gtk.WidgetPaintable.new(win).snapshot(sn, w, h)
    node = sn.to_node()
    if node is None: return False
    win.get_native().get_renderer().render_texture(node, None).save_to_png(os.path.join(OUT, name + ".png"))
    print("saved", name, w, h, flush=True); return True

class T(A.SnipshotApp):
    def apply_settings(self): pass
    def activate_command(self, args):
        rng = np.random.default_rng(3)
        img = im.blank(1600, 900, (60, 90, 140, 255)); img[200:700, 300:1300] = (235, 238, 242, 255)
        self.steps = []
        sel = CAP.RegionSelector(img, lambda *a: None)
        sel.shared.start, sel.shared.cur = (400.0, 260.0), (1100.0, 560.0); sel.shared.hover = sel.shared.cur
        sel.show()
        host = A.Gtk.Window()      # a parent for the prefs / dialogs
        queue = [("overlay", lambda: snap(sel.shared.windows[0], "overlay"))]
        win = self.open_editor(img, name="Test")
        def after():
            sel.shared.windows and [w.destroy() for w in sel.shared.windows]
            self.show_preferences(win)
        self.i = 0
        def tick():
            self.i += 1
            if self.i == 3: snap(sel.shared.windows[0], "overlay")
            if self.i == 4:
                [w.destroy() for w in sel.shared.windows]; self.show_preferences(win)
            if self.i == 7:
                prefs = [w for w in Gtk.Window.list_toplevels() if w.get_title() == "Snipshot preferences"][0]
                snap(prefs, "prefs")
                prefs.destroy(); DLG.resize_dialog(win, 1600, 900, lambda *a: None)
            if self.i == 10:
                d = [w for w in Gtk.Window.list_toplevels() if w.get_title() == "Resize image"][0]
                snap(d, "dlg_resize"); d.close(); DLG.adjust_dialog(win, lambda *a: None, lambda *a: None, lambda: None)
            if self.i == 13:
                d = [w for w in Gtk.Window.list_toplevels() if w.get_title() == "Adjust colours"][0]
                snap(d, "dlg_adjust"); self.quit_all(); return False
            return True
        GLib.timeout_add(700, tick)

T().run([sys.argv[0]])
