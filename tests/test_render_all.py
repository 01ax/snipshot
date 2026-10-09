import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imaging as im, model as M, render as R

W, H = 900, 560
pil = Image.new("RGB", (W, H), (236, 240, 245))
d = ImageDraw.Draw(pil)
try:
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    fs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
except Exception:
    f = fs = ImageFont.load_default()
d.rectangle([0, 0, W, 40], fill=(40, 60, 110))
d.text((14, 8), "Customer portal - account 8841-2290", font=f, fill="white")
for i, line in enumerate(["Name:      Alex Morgan", "Email:     alex.morgan@example.com", "Card:      4111 1111 1111 1111",
                          "Password:  hunter2-secret!", "Server:    203.0.113.5 (RDP)", "Notes:     renewal due 31 Oct"]):
    d.text((30, 70 + i * 34), line, font=f, fill=(20, 20, 30))
for i in range(0, W, 30):
    d.line([(i, 300), (i + 20, 520)], fill=(180, 190, 210), width=3)
scene = M.Scene(im.from_pil(pil))

def add(kind, x1, y1, x2, y2, **kw):
    o = M.Obj(kind, x1, y1, x2, y2, **kw); scene.add(o); return o

add("rect", 20, 60, 380, 100)
add("ellipse", 400, 60, 560, 100, line_color=M.BLUE, thickness=3)
add("line", 600, 70, 700, 110)
add("arrow", 600, 160, 840, 100, thickness=3)
add("arrow", 600, 200, 840, 240, arrowheads=M.ARROW_BOTH, line_color=M.BLUE)
fh = M.new_obj("freehand", 580, 270); fh.points = [(580,270),(610,290),(640,262),(670,300),(700,268),(740,300)]; scene.add(fh)
t = add("text", 30, 290, 330, 340, fill_color=(1,1,0.8,1)); t.text = "Check this field first"
sp = add("speech", 30, 380, 300, 450); sp.text = "Looks wrong!"; sp.tail = (230, 520)
for i, (sx, sy) in enumerate([(360, 330), (410, 330), (460, 330)]):
    add("step", sx, sy, sx + 30, sy + 30)
# obfuscate: pixelate the card number, blur the password
add("obfuscate", 140, 138, 470, 170, preset="pixelize", pixel_size=8)
add("obfuscate", 140, 172, 470, 204, preset="blur", blur_radius=8)
add("highlight", 150, 210, 520, 240, preset="text")
out = R.render_scene(scene)
out.write_to_png(sys.argv[1])
print("rendered", out.get_width(), out.get_height())
