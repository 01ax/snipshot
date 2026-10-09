"""Tests for config.py and the model's geometry. Run: python3 -I test_config.py"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="snipshot-test-")
os.environ["SNIPSHOT_CONFIG_DIR"] = tmp
import config as C
import model as M
import numpy as np

fails = 0


def check(name, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", name, extra)


# ---- filename patterns
when = datetime(2026, 10, 9, 14, 5, 7)
check("pattern expands date/time", C.expand_pattern("S_${YYYY}-${MM}-${DD}_${hh}-${mm}-${ss}", when) == "S_2026-10-09_14-05-07")
check("pattern ${title} + unknown var kept", C.expand_pattern("${title}-${nope}", when, "My Win") == "My Win-${nope}")
check("illegal characters replaced", "/" not in C.expand_pattern("a/b:c*d", when) and C.expand_pattern("a/b:c*d", when) == "a_b_c_d")
check("empty pattern -> safe name", C.expand_pattern("   ", when) == "Screenshot")
p1 = C.unique_path(tmp, "shot", "png")
open(p1, "w").close()
p2 = C.unique_path(tmp, "shot", "png")
check("unique_path never overwrites", p1 != p2 and p2.endswith("shot_2.png"))

# ---- config persistence & validation
cfg = C.Config(os.path.join(tmp, "c.json"))
cfg["output_dir"] = "~/x"
cfg["jpg_quality"] = 77
cfg.save()
cfg2 = C.Config(os.path.join(tmp, "c.json"))
check("config round-trips", cfg2["output_dir"] == "~/x" and cfg2["jpg_quality"] == 77)
open(os.path.join(tmp, "bad.json"), "w").write('{"jpg_quality": "lots", "format": "gif", "after_capture": 5}')
cfg3 = C.Config(os.path.join(tmp, "bad.json"))
check("wrong-typed values ignored, invalid format -> png", cfg3["jpg_quality"] == 90 and cfg3["format"] == "png" and cfg3["after_capture"] == ["ask"])
open(os.path.join(tmp, "broken.json"), "w").write("{not json")
check("corrupt file -> defaults", C.Config(os.path.join(tmp, "broken.json"))["format"] == "png")
check("recent files de-duplicated and capped", (lambda c: [c.remember_file(f"/a/{i}") for i in range(15)] and (c.remember_file("/a/3"), len(c["recent_files"]), c["recent_files"][0]))(C.Config(os.path.join(tmp, "r.json")))[1:] == (10, "/a/3"))

# ---- model geometry
r = M.Obj("rect", 10, 10, 110, 60)
check("unfilled rect: inside is NOT a hit, outline is", not M.hit(r, 60, 35) and M.hit(r, 10, 35) and M.hit(r, 60, 11))
r.p["fill_color"] = (1, 1, 1, 1)
check("filled rect: inside is a hit", M.hit(r, 60, 35))
e = M.Obj("ellipse", 0, 0, 100, 60)
check("unfilled ellipse: centre not hit, edge hit", not M.hit(e, 50, 30) and M.hit(e, 0, 30) and M.hit(e, 50, 0))
ln = M.Obj("line", 0, 0, 100, 0)
check("line hit near, miss far", M.hit(ln, 50, 3) and not M.hit(ln, 50, 20))
st = M.Obj("step", 0, 0, 30, 30)
check("step label hit inside circle, not in corner", M.hit(st, 15, 15) and not M.hit(st, 1, 1))
fh = M.new_obj("freehand", 0, 0); fh.points = [(0, 0), (50, 0), (50, 50)]
check("freehand hit along path", M.hit(fh, 25, 1) and M.hit(fh, 49, 30) and not M.hit(fh, 10, 40))

sc = M.Scene(np.zeros((100, 200, 4), dtype=np.uint8))
a = sc.add(M.Obj("rect", 0, 0, 50, 50, fill_color=(1, 0, 0, 1)))
b = sc.add(M.Obj("rect", 25, 25, 75, 75, fill_color=(0, 1, 0, 1)))
check("top_hit returns the topmost object", sc.top_hit(30, 30) is b and sc.top_hit(5, 5) is a and sc.top_hit(150, 90) is None)
sc.raise_to_top(a)
check("raise_to_top changes hit order", sc.top_hit(30, 30) is a)
s1, s2, s3 = (sc.add(M.Obj("step", i * 40, 0, i * 40 + 30, 30)) for i in range(3))
check("step numbers count in order from counter_start", [sc.step_number(s) for s in (s1, s2, s3)] == [1, 2, 3])
sc.remove(s2)
check("step labels renumber after delete", [sc.step_number(s) for s in (s1, s3)] == [1, 2])
sc.counter_start = 5
check("counter start offsets numbers", sc.step_number(s1) == 5)

# handles / dragging
r = M.Obj("rect", 10, 10, 110, 60)
check("8 handles on a rect", len(M.handles(r)) == 8)
M.drag_handle(r, "se", 200, 100)
check("drag SE handle resizes", r.rect() == (10, 10, 190, 90))
M.drag_handle(r, "nw", 300, 300)               # dragged past the opposite corner: flips, stays valid
check("dragging past the opposite corner flips cleanly", r.rect()[2] >= 0 and r.rect()[3] >= 0)
ar = M.Obj("arrow", 0, 0, 50, 50)
check("arrow has 2 end handles", [h[0] for h in M.handles(ar)] == ["start", "end"])
M.drag_handle(ar, "end", 80, 20)
check("drag arrow end", (ar.x2, ar.y2) == (80, 20))
sq = M.Obj("step", 0, 0, 30, 30)
M.drag_handle(sq, "se", 60, 40)
check("step label stays square", abs(sq.rect()[2] - sq.rect()[3]) < 1e-9)
x2, y2 = M.constrain_end("line", 0, 0, 100, 30)
check("shift-constrain snaps a line to 0 degrees", abs(y2) < 1e-6 and x2 > 90)
x2, y2 = M.constrain_end("rect", 0, 0, 100, 30)
check("shift-constrain makes a square", abs(x2) == abs(y2) == 100)

# undo snapshots are independent copies
sc2 = M.Scene(np.zeros((10, 10, 4), dtype=np.uint8))
o = sc2.add(M.Obj("rect", 0, 0, 5, 5))
snap = sc2.snapshot()
o.x2 = 99
sc2.add(M.Obj("rect", 1, 1, 2, 2))
sc2.restore(snap)
check("snapshot/restore returns to the earlier state", len(sc2.objects) == 1 and sc2.objects[0].x2 == 5)
sc2.objects[0].x2 = 7
check("restored objects do not alias the snapshot", snap["objects"][0].x2 == 5)

# rotate keeps annotations on the same pixels
sc3 = M.Scene(np.zeros((40, 100, 4), dtype=np.uint8))
tag = sc3.add(M.Obj("rect", 10, 5, 30, 15))
sc3.rotate(clockwise=True)
check("rotate CW swaps the canvas size", sc3.size == (40, 100))
check("rotate CW moves annotation (10,5)->(35,10)", (round(tag.x1), round(tag.y1)) == (35, 10), str((tag.x1, tag.y1)))
sc3.rotate(clockwise=False)
check("rotate CCW undoes it", sc3.size == (100, 40) and (round(tag.x1), round(tag.y1)) == (10, 5))

print("\nFAILED" if fails else "\nALL PASSED", fails or "")
import shutil; shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fails else 0)
