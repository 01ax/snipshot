"""Ctrl+C in the editor copies the WHOLE image with its edits; Ctrl+Shift+C copies only the selected objects.
Real key presses inside the PRIVATE headless session: tools/headless_session.sh python3 -I tests/test_editor_copy.py"""
import os
import sys
import tempfile
import threading
import time

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("Refusing to run: start this with tools/headless_session.sh.")
os.environ["SNIPSHOT_CONFIG_DIR"] = tempfile.mkdtemp(prefix="snipshot-ec-")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402
import app as A
import imaging as im
import model as M
import output
import remote_input

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


class T(A.SnipshotApp):
    def apply_settings(self):
        pass

    def activate_command(self, args):
        self.hold()
        base = im.blank(300, 200, (230, 230, 235, 255))
        self.win = self.open_editor(base, name="copytest")
        self.base = base.copy()
        o = M.new_obj("rect", 40, 40)
        o.set_rect(40, 40, 120, 80)
        o.p.update(line_color=(255, 0, 0, 255), fill_color=(255, 0, 0, 255), thickness=2, shadow=False)
        self.win.canvas.scene.add(o)
        self.obj = o
        threading.Thread(target=self.drive, daemon=True).start()

    def on_main(self, fn):
        ev, box = threading.Event(), []
        GLib.idle_add(lambda: (box.append(fn()), ev.set(), False)[-1])
        ev.wait(15)
        return box[0] if box else None

    def read_clip(self):
        got = []
        ev = threading.Event()

        def ask():
            output.read_clipboard_image(lambda arr: (got.append(arr), ev.set()))
            return False
        GLib.idle_add(ask)
        ev.wait(10)
        return got[0] if got else None

    def drive(self):
        try:
            time.sleep(2.5)
            inp = remote_input.RemoteInput()
            inp.move(500, 400); inp.move(510, 410)
            self.on_main(lambda: (setattr(self.win.canvas, "selection", [self.obj]), self.win.canvas.area.queue_draw(), False)[-1])
            output.copy_text("sentinel")                                   # something else on the clipboard first
            # an object is selected: Ctrl+C must still copy the WHOLE image, edits included
            inp.chord(["Control_L"], "c")
            time.sleep(0.5)
            clip = self.read_clip()
            check("Ctrl+C put an image on the clipboard", clip is not None)
            if clip is not None:
                check("it is the whole image (300 x 200), not just the selected rectangle", clip.shape[:2] == (200, 300), str(clip.shape))
                red = int(clip[80, 100, 2]) > 200 and int(clip[80, 100, 1]) < 60            # BGRA: inside the rectangle
                bg = tuple(int(v) for v in clip[10, 10, :3]) == (235, 230, 230)
                check("the edit (red rectangle) is in it, and the untouched background too", red and bg, str((clip[80, 100], clip[10, 10])))
                check("it equals what Save would write", np.array_equal(clip[..., :3], self.on_main(self.win._arr)[..., :3]))
            # Ctrl+Shift+C copies only the selected object(s), for pasting into the picture again
            output.copy_text("sentinel2")
            inp.chord(["Control_L", "Shift_L"], "c")
            time.sleep(0.5)
            import canvas as CV

            check("Ctrl+Shift+C copies the selected object into the editor's object clipboard", len(CV._object_clipboard) == 1, str(len(CV._object_clipboard)))
            inp.close()
        except Exception as e:                                             # noqa: BLE001
            import traceback
            traceback.print_exc()
            check("test ran to the end", False, repr(e))
        GLib.idle_add(self.quit)


T().run([])
print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
