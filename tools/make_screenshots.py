"""Takes the screenshots used in the README, inside a PRIVATE invisible GNOME session (nothing appears on a real screen):

    SNIPSHOT_HL_RES=1920x1080 SNIPSHOT_HL_EXTENSIONS="$PWD/shell-extension" \\
        tools/headless_session.sh python3 -I tools/make_screenshots.py OUTPUT_DIR

It opens a small demo file in GNOME Text Editor (a made-up API key for the pixelate demo), then drives the real Snipshot
with synthetic mouse and key events: the capture overlay in each mode, the after-capture menu, the editor with
annotations, the OCR result, Preferences, and the recording controls in the top bar. Raw full-screen grabs go to
OUTPUT_DIR/raw; the cropped images used by the README go to OUTPUT_DIR."""
import os
import subprocess
import sys
import tempfile
import threading
import time

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("Refusing to run: start this with tools/headless_session.sh (it must never grab a real screen).")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
RAW = os.path.join(OUT, "raw")
os.makedirs(RAW, exist_ok=True)
CFG_DIR = tempfile.mkdtemp(prefix="snipshot-shots-")
os.environ["SNIPSHOT_CONFIG_DIR"] = CFG_DIR
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402
from PIL import Image  # noqa: E402
import app as A
import model as M
import prefs as PR
import remote_input

DEMO = '''"""Upload a screenshot to the team wiki."""
import os

import requests

API_URL = "https://wiki.example.com/api/v2/attachments"
API_KEY = "sk-live-9f3a7c21d4e84b6fa0c1"        # made up, for this demo only


def upload(path, page_id):
    """Send one image to a wiki page and return its public URL."""
    with open(path, "rb") as fh:
        reply = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {API_KEY}"},
            files={"file": fh},
            data={"page": page_id},
            timeout=30,
        )
    reply.raise_for_status()
    return reply.json()["url"]


if __name__ == "__main__":
    print(upload(os.environ["SHOT"], page_id=42))
'''


def grab(name):
    """Full-screen grab of the private desktop to OUT/raw/name.png."""
    subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "grab_png.py"), os.path.join(RAW, name)], timeout=40, check=False)
    src = os.path.join(RAW, f"{name}-0.png")
    dst = os.path.join(RAW, f"{name}.png")
    if os.path.exists(src):
        os.replace(src, dst)
    return dst


class Shots(A.SnipshotApp):
    def apply_settings(self):
        pass                                             # no tray icon in this session

    def activate_command(self, args):
        self.hold()
        self.cfg["capture_cursor"] = False
        self.cfg["record_dir"] = os.path.join(CFG_DIR, "videos")
        self.cfg["record_countdown"] = 0
        self.cfg["record_system_audio"] = False
        self.cfg["output_dir"] = os.path.join(CFG_DIR, "pics")
        threading.Thread(target=self.drive, daemon=True).start()

    def on_main(self, fn, *args):
        ev, box = threading.Event(), []

        def run():
            try:
                box.append(fn(*args))
            except Exception as e:                          # noqa: BLE001
                box.append(e)
            ev.set()
            return False
        GLib.idle_add(run)
        ev.wait(30)
        if box and isinstance(box[0], Exception):
            raise box[0]
        return box[0] if box else None

    def drive(self):
        try:
            scenes(self)
        except Exception:                                   # noqa: BLE001
            import traceback
            traceback.print_exc()
        GLib.idle_add(self.quit)


def scenes(app):
    inp = remote_input.RemoteInput()            # first: its warm-up key presses must not land in a window
    work = "/tmp/wiki-tools"                      # a neutral-looking folder name for the window title
    os.makedirs(work, exist_ok=True)
    demo = os.path.join(work, "upload_shot.py")
    open(demo, "w").write(DEMO)
    sock = [f for f in os.listdir(os.environ["XDG_RUNTIME_DIR"]) if f.startswith("wayland-") and not f.endswith(".lock")][0]
    editor = subprocess.Popen(["gnome-text-editor", demo], env=dict(os.environ, WAYLAND_DISPLAY=sock, GDK_BACKEND="wayland"),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)
    grab("desktop")                                          # for choosing coordinates

    def overlay(mode):
        app.on_main(lambda: app.capture_region(mode=mode))
        time.sleep(3.5)
        inp.move(500, 300); inp.move(510, 310)

    # 1. screenshot overlay, mid-drag; then the after-capture menu
    r = REGION
    overlay("screenshot")
    inp.key("z")                                    # magnifier off: it would sit on top of the selection in a still image
    inp.move(*r[0]); inp.button(True)
    for i in range(1, 9):
        inp.move(r[0][0] + (r[1][0] - r[0][0]) * i / 8, r[0][1] + (r[1][1] - r[0][1]) * i / 8, settle=0.05)
    time.sleep(0.6)
    grab("overlay-screenshot")
    inp.button(False)
    time.sleep(2.0)
    grab("after-capture")

    # 2. the editor with annotations
    inp.key("e")
    time.sleep(3.0)
    win = app.editors[-1]
    app.on_main(lambda: annotate(win))
    time.sleep(1.5)
    grab("editor")
    app.on_main(lambda: (setattr(win, "_closing_ok", True), win.close()))
    time.sleep(1.0)

    # 3. record mode: choose an area, wait for Start
    overlay("record")
    inp.drag(*RECORD_REGION)
    time.sleep(0.8)
    grab("overlay-record")
    inp.key("Escape")
    time.sleep(1.0)

    # 4. text mode: drag over code (mid-drag), release, the result window
    overlay("ocr")
    inp.key("z")
    t = TEXT_REGION
    inp.move(*t[0]); inp.button(True)
    for i in range(1, 9):
        inp.move(t[0][0] + (t[1][0] - t[0][0]) * i / 8, t[0][1] + (t[1][1] - t[0][1]) * i / 8, settle=0.05)
    time.sleep(0.6)
    grab("overlay-text")
    inp.button(False)
    time.sleep(5.0)
    grab("ocr-result")
    app.on_main(lambda: app._ocr_win and app._ocr_win.close())
    time.sleep(1.0)

    # 5. preferences, Recording tab (shown with the normal defaults; restored afterwards for the recording below)
    saved = {k: app.cfg[k] for k in ("record_dir", "record_countdown", "record_system_audio")}
    app.cfg["record_dir"], app.cfg["record_countdown"], app.cfg["record_system_audio"] = "~/Videos/Screencasts", 3, True

    def prefs():
        w = PR.PrefsWindow(app)
        w.present()
        nb = w.get_child().get_first_child()
        nb.set_current_page(3)
        app._prefs_shot = w
    app.on_main(prefs)
    time.sleep(2.0)
    grab("preferences-recording")
    app.on_main(lambda: app._prefs_shot.close())
    app.cfg.update(saved)
    time.sleep(1.0)

    # 6. recording controls in the top bar: recording, then the hover tooltip, then paused
    mon = A.SCN.list_monitors()[0]
    target = {"kind": "monitor", "connector": mon.connector, "size": (mon.pw, mon.ph), "crop": None}
    app.on_main(lambda: app.begin_recording(target, dict(system=False, mic=False, cursor=True), 0))
    time.sleep(6.0)
    inp.move(900, 500)
    grab("recording-controls")
    inp.move(*PAUSE_BUTTON)
    time.sleep(1.4)
    grab("recording-tooltip")
    inp.button(True); inp.button(False)
    time.sleep(2.5)
    inp.move(*DELETE_BUTTON)
    time.sleep(1.4)
    grab("recording-paused")
    app.on_main(app.stop_recording)
    time.sleep(3.0)
    inp.close()
    editor.terminate()
    make_final_images()


CROPS = {                       # name -> (raw grab, (left, top, right, bottom))
    "capture-overlay": ("overlay-screenshot", (440, 0, 1480, 880)),
    "after-capture": ("after-capture", (690, 240, 1230, 880)),
    "editor": ("editor", (440, 186, 1480, 926)),
    "record-overlay": ("overlay-record", (440, 0, 1480, 900)),
    "text-overlay": ("overlay-text", (440, 0, 1480, 880)),
    "text-result": ("ocr-result", (590, 280, 1330, 830)),
    "preferences": ("preferences-recording", (660, 170, 1260, 950)),
}


def make_final_images():
    """Crop the raw grabs into the README images and write them next to the raw folder."""
    for name, (raw, box) in CROPS.items():
        src = os.path.join(RAW, raw + ".png")
        if os.path.exists(src):
            Image.open(src).convert("RGB").crop(box).save(os.path.join(OUT, name + ".png"), optimize=True)
    # the recording controls: the top-right of the screen, enlarged 2x, recording (with the tooltip) above paused
    parts = []
    for raw in ("recording-tooltip", "recording-paused"):
        src = os.path.join(RAW, raw + ".png")
        if os.path.exists(src):
            im = Image.open(src).convert("RGB").crop((1380, 0, 1920, 78))
            parts.append(im.resize((im.width * 2, im.height * 2), Image.LANCZOS))
    if parts:
        sheet = Image.new("RGB", (parts[0].width, sum(p.height for p in parts) + 8 * (len(parts) - 1)), (255, 255, 255))
        y = 0
        for p in parts:
            sheet.paste(p, (0, y))
            y += p.height + 8
        sheet.save(os.path.join(OUT, "recording-controls.png"), optimize=True)


def annotate(win):
    """Rectangle, arrow, a note and a pixelated 'secret' on the capture (coordinates are image pixels)."""
    c = win.canvas
    img_w, img_h = c.scene.size
    for spec in ANNOTATIONS(img_w, img_h):
        kind = spec["kind"]
        o = M.new_obj(kind, *spec["p1"])
        if "p2" in spec:
            o.x2, o.y2 = spec["p2"]
        o.p.update(spec.get("props", {}))
        if "text" in spec:
            o.text = spec["text"]
        c.scene.add(o)
    c.selection = []
    c.area.queue_draw()
    win._changed()


# ---- coordinates in screen pixels on the 1920x1080 private desktop (chosen by looking at raw/desktop.png)
REGION = ((614, 458), (1290, 704))                 # the screenshot drag (screen pixels); its top-left is image pixel (0, 0)
RECORD_REGION = ((610, 296), (1310, 816))          # the whole editor window
TEXT_REGION = ((616, 458), (1270, 590))            # two lines of code and a bit more
PAUSE_BUTTON = (1620, 16)
DELETE_BUTTON = (1690, 16)


def ANNOTATIONS(w, h):
    red = (0.86, 0.15, 0.15, 1.0)
    # screen pixel -> image pixel is (x - 614, y - 458): the API_KEY line is at y 490 -> 32, its key text x 712..943 -> 98..329
    return [
        dict(kind="obfuscate", p1=(97, 23), p2=(331, 42), props=dict(preset="pixelize", pixel_size=7)),
        dict(kind="rect", p1=(2, 22), p2=(w - 6, 44), props=dict(line_color=red, thickness=3, shadow=False)),
        dict(kind="arrow", p1=(388, 70), p2=(322, 47), props=dict(line_color=red, thickness=4, shadow=False)),
        dict(kind="text", p1=(366, 52), p2=(672, 90), text="key hidden before sharing",
             props=dict(line_color=red, thickness=0, font_size=14.0, bold=True, shadow=False)),
    ]


if __name__ == "__main__":
    Shots().run([])
    print("raw grabs in", RAW)
