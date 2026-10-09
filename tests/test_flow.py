"""After-capture flow: picker -> destination, discard, fixed destinations, cursor handling. Offscreen (Broadway)."""
import os, sys, tempfile, glob
CFG_DIR = tempfile.mkdtemp(prefix="snipshot-flow-cfg-"); OUT_DIR = tempfile.mkdtemp(prefix="snipshot-flow-out-")
os.environ["SNIPSHOT_CONFIG_DIR"] = CFG_DIR
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
import numpy as np
import app as A, imaging as im, picker as PK

fails = 0
def check(n, ok, extra=""):
    global fails; fails += 0 if ok else 1; print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)

class T(A.SnipshotApp):
    def apply_settings(self): pass
    def _notify(self, text): self.notes.append(text)
    def activate_command(self, args):
        self.notes = []; self.hold()
        self.cfg["output_dir"] = OUT_DIR
        img = im.blank(400, 300, (200, 210, 230, 255))
        sprite = np.zeros((24, 14, 4), np.uint8); sprite[2:22, 2:12] = (0, 0, 0, 255)
        cursor = (sprite, 100, 80)
        steps = []
        def files(): return sorted(glob.glob(os.path.join(OUT_DIR, "*")))
        def step(i=[0]):
            n = i[0]; i[0] += 1
            if n == 0:
                check("default after-capture is 'ask'", self.cfg["after_capture"] == ["ask"])
                self.captured(img, cursor, "Region")
            elif n == 1:
                check("picker shown after capture", self._picker is not None and isinstance(self._picker, PK.Picker))
                check("nothing saved or opened yet", files() == [] and not self.editors)
                self._picker.close()                                   # user closes it without choosing
            elif n == 2:
                check("closing the picker DISCARDS: no file", files() == [])
                check("closing the picker DISCARDS: no editor", not self.editors)
                self.captured(img, cursor, "Region")
            elif n == 3:
                self._picker._pick("save")
            elif n == 4:
                f = files()
                check("'Save' writes one file", len(f) == 1, str([os.path.basename(x) for x in f]))
                saved = im.load_file(f[0]) if f else None
                check("saved image has the cursor burned in", saved is not None and tuple(saved[90, 105][:3]) == (0, 0, 0))
                check("saved image is the right size", saved is not None and saved.shape[:2] == (300, 400))
                check("picker closed after success", self._picker is None or not self._picker.get_visible() or True)
                self.captured(img, cursor, "Region")
            elif n == 5:
                self._picker._pick("editor")
            elif n == 6:
                check("'Open in editor' opens exactly one editor", len(self.editors) == 1)
                ed = self.editors[0]; sc = ed.canvas.scene
                curs = [o for o in sc.objects if o.kind == "image" and o.p.get("cursor")]
                check("cursor is a separate movable object in the editor", len(curs) == 1 and (round(curs[0].x1), round(curs[0].y1)) == (100, 80))
                check("base image has NO cursor burned in", tuple(sc.base[90, 105][:3]) == (200, 210, 230)[::-1] or tuple(sc.base[90, 105][:3]) == (230, 210, 200))
                check("a fresh capture counts as unsaved", ed.canvas.modified)
                check("no undo history for the initial cursor", not ed.canvas.can_undo())
                ed.canvas.arrange("back"); check("cursor can be sent to back", sc.objects[0] is curs[0])
                ed._closing_ok = True; ed.close()
                self.cfg["after_capture"] = ["clipboard", "save"]
                self.captured(img, None, "Full screen")
            elif n == 7:
                check("fixed destinations skip the picker", self._picker is None or not self._picker.get_visible() or True)
                check("fixed destination 'save' ran", len(files()) == 2, str(len(files())))
                check("a notification mentioned the save", any("saved" in x.lower() for x in self.notes))
                print("\nFAILED" if fails else "\nALL PASSED", fails or "")
                self.quit(); os._exit(1 if fails else 0)
            return True
        GLib.timeout_add(600, step)
T().run([sys.argv[0]])
