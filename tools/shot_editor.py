"""Render the real editor window offscreen (Broadway) for a visual check."""
import os, sys, tempfile
os.environ["SNIPSHOT_CONFIG_DIR"] = tempfile.mkdtemp(prefix="snipshot-ui-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import app as A, imaging as im, model as M

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)

def sample():
    W, H = 1000, 600
    pil = Image.new("RGB", (W, H), (236, 240, 245)); d = ImageDraw.Draw(pil)
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    d.rectangle([0, 0, W, 44], fill=(40, 60, 110)); d.text((14, 9), "Customer portal - account 8841-2290", font=f, fill="white")
    for i, line in enumerate(["Name:      Alex Morgan", "Email:     alex.morgan@example.com", "Card:      4111 1111 1111 1111",
                              "Password:  hunter2-secret!", "Server:    203.0.113.5 (RDP)"]):
        d.text((30, 80 + i * 38), line, font=f, fill=(20, 20, 30))
    return im.from_pil(pil)

class T(A.SnipshotApp):
    def apply_settings(self): pass                      # no tray in the test
    def activate_command(self, args):
        win = self.open_editor(sample(), name="Region")
        sc, c = win.canvas, win.canvas
        def add(kind, *a, **kw):
            o = M.Obj(kind, *a, **kw); sc.scene.add(o); return o
        add("rect", 24, 70, 420, 118)
        o = add("obfuscate", 150, 156, 480, 196, preset="pixelize", pixel_size=9)
        add("obfuscate", 170, 196, 470, 236, preset="blur", blur_radius=9)
        add("arrow", 700, 300, 520, 205, thickness=3)
        s = add("step", 520, 150, 550, 180)
        t = add("text", 600, 120, 900, 170); t.text = "Redact before sharing"
        steps = ["select", "obfuscate"]
        state = {"i": 0}
        def go():
            i = state["i"]; state["i"] += 1
            if i == 0:
                win.canvas.select([o]); win.tool_buttons["select"].set_active(True)
            elif i == 2:
                self.snap(win, "editor_obfuscate_selected")
                win.tool_buttons["obfuscate"].set_active(True)
            elif i == 4:
                self.snap(win, "editor_obfuscate_tool")
                win.canvas.select([t]); win.tool_buttons["select"].set_active(True)
            elif i == 6:
                self.snap(win, "editor_text_selected")
                self.quit_all(); return False
            return True
        GLib.timeout_add(900, go)
    def snap(self, win, name):
        w, h = win.get_width(), win.get_height()
        sn = Gtk.Snapshot(); Gtk.WidgetPaintable.new(win).snapshot(sn, w, h)
        node = sn.to_node()
        if node is None: print("EMPTY", name); return
        tex = win.get_native().get_renderer().render_texture(node, None)
        tex.save_to_png(os.path.join(OUT, name + ".png")); print("saved", name, w, h, flush=True)

T().run([sys.argv[0]])
