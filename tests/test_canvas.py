"""Drives the Canvas with fake gestures under the Broadway backend and checks the resulting scene."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib
import imaging as im, model as M
import canvas as C

fails = 0
def check(n, ok, extra=""):
    global fails; fails += 0 if ok else 1; print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)

class G:                                   # stand-in for Gtk.GestureDrag
    def __init__(self, sx, sy, shift=False, ctrl=False):
        self.sx, self.sy, self.m = sx, sy, 0
        if shift: self.m |= Gdk.ModifierType.SHIFT_MASK
        if ctrl: self.m |= Gdk.ModifierType.CONTROL_MASK
    def get_current_event_state(self): return Gdk.ModifierType(self.m)
    def get_start_point(self): return True, self.sx, self.sy

class App(Gtk.Application):
    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self); win.set_default_size(900, 700)
        base = im.blank(600, 400, (230, 235, 240, 255))
        self.scene = M.Scene(base)
        self.c = C.Canvas(self.scene)
        win.set_child(self.c); win.present()
        GLib.timeout_add(500, self.run_tests)

    def w(self, ix, iy):                   # image coords -> widget coords
        return self.c.to_widget(ix, iy)

    def drag(self, p1, p2, **mods):
        c = self.c
        (x1, y1), (x2, y2) = self.w(*p1), self.w(*p2)
        g = G(x1, y1, **mods)
        c._drag_begin(g, x1, y1); c._drag_update(g, x2 - x1, y2 - y1); c._drag_end(g, x2 - x1, y2 - y1)

    def run_tests(self):
        c, sc = self.c, self.scene
        c.set_zoom(1.0)
        c.set_tool("rect"); self.drag((50, 50), (200, 120))
        check("draw rect by dragging", len(sc.objects) == 1 and sc.objects[0].kind == "rect")
        r = sc.objects[0]
        check("rect geometry ~ drag (zoom 1)", all(abs(a - b) < 1.5 for a, b in zip(r.rect(), (50, 50, 150, 70))), str(r.rect()))
        check("tool auto-returns via on_tool_done hook & new object selected", c.selection == [r])
        check("undo stack has the creation", len(c.undo_stack) == 1)
        c.undo(); check("undo removes it", len(sc.objects) == 0)
        c.redo(); check("redo brings it back", len(sc.objects) == 1 and sc.objects[0].kind == "rect")
        r = sc.objects[0]

        c.set_tool("select")
        self.drag((100, 80), (100, 80))                       # click inside an UNFILLED rect: should not select
        # now click on its edge
        self.drag((80, 50), (80, 50))
        check("clicking the outline selects it", c.selection == [r])
        self.drag((80, 50), (110, 70))                        # drag by outline (not a handle) = move
        check("dragging moves the object", abs(r.x1 - 80) < 2 and abs(r.y1 - 70) < 2, str(r.rect()))
        check("move recorded as one undo step", len(c.undo_stack) == 2)
        # resize via SE handle
        x2, y2 = r.x2, r.y2
        self.drag((x2, y2), (x2 + 40, y2 + 30))
        check("dragging the SE handle resizes", abs(r.x2 - (x2 + 40)) < 2 and abs(r.y2 - (y2 + 30)) < 2)

        # arrow + shift constrain
        c.set_tool("arrow"); self.drag((300, 300), (400, 330), shift=True)
        a = sc.objects[-1]
        check("shift snaps the arrow to 0 degrees", abs(a.y2 - a.y1) < 1e-6, f"({a.x1:.0f},{a.y1:.0f})->({a.x2:.0f},{a.y2:.0f})")

        # step labels: click places 30x30 centred, numbered in order
        c.set_tool("step"); self.drag((100, 250), (100, 250)); c.set_tool("step"); self.drag((160, 250), (160, 250))
        steps = [o for o in sc.objects if o.kind == "step"]
        check("two step labels, 30x30, centred on the click", len(steps) == 2 and abs(steps[0].rect()[2] - 30) < 1 and abs(steps[0].x1 - 85) < 2, str(steps[0].rect()))
        check("step numbers 1,2", [sc.step_number(s) for s in steps] == [1, 2])

        # obfuscate drawn over the step labels
        c.set_tool("obfuscate"); self.drag((70, 230), (200, 290))
        ob = sc.objects[-1]
        check("obfuscate tool creates an obfuscate object with default pixelize", ob.kind == "obfuscate" and ob.p["preset"] == "pixelize")
        c.set_prop("pixel_size", 25)
        check("set_prop changes the selected obfuscate", ob.p["pixel_size"] == 25 and c.defaults["obfuscate"]["pixel_size"] == 25)
        c.set_prop("preset", "blur"); c.set_prop("blur_radius", 14)
        check("switch to blur + radius", ob.p["preset"] == "blur" and ob.p["blur_radius"] == 14)
        out = c.export_array()
        check("export includes the effect (region differs from base)", not (out[240:280, 80:190] == sc.base[240:280, 80:190]).all())

        # delete / copy / paste / arrange
        n = len(sc.objects); c.select([ob]); c.copy_selected(); c.paste_objects()
        check("paste duplicates the object", len(sc.objects) == n + 1 and c.selection[0] is not ob and c.selection[0].uid != ob.uid)
        c.delete_selected(); check("delete removes the selection", len(sc.objects) == n)
        c.undo(); check("undo restores the deleted object", len(sc.objects) == n + 1)

        # text: drag a text box, type, commit
        c.set_tool("text"); self.drag((300, 60), (480, 110))
        t = [o for o in sc.objects if o.kind == "text"][-1]
        check("text tool opens an in-place editor", c._edit is not None and c._edit["obj"] is t)
        c._edit["view"].get_buffer().set_text("Hello world, this wraps onto lines")
        c._finish_text_edit()
        check("text committed and box grew to fit", t.text.startswith("Hello") and t.rect()[3] >= 50, str(t.rect()))
        c.set_tool("text"); self.drag((300, 300), (320, 320))
        t2 = [o for o in sc.objects if o.kind == "text"][-1]
        c._finish_text_edit()
        check("empty text box is discarded", t2 not in sc.objects)

        # crop
        c.set_tool("crop"); self.drag((100, 100), (400, 300))
        check("crop rectangle shown", c.crop is not None and abs(c.crop.rect()[2] - 300) < 2)
        before = sc.size
        c.crop_confirm()
        check("crop confirmed shrinks the image to the crop", sc.size == (300, 200), str(sc.size))
        check("annotations shifted with the crop", all(o.x1 >= -300 for o in sc.objects))
        c.undo(); check("undo restores the original size", sc.size == before)
        c.rotate(True); check("rotate CW swaps dimensions", sc.size == (before[1], before[0]))
        c.undo()
        # vertical cut removes a strip
        c.set_tool("crop"); c.crop = None; c.set_prop("mode", "vertical"); c.defaults["crop"]["mode"] = "vertical"
        self.drag((100, 10), (160, 30)); w0 = sc.size[0]
        c.crop_confirm(); check("vertical cut removes a 60px strip", sc.size[0] == w0 - 60, str(sc.size))
        # auto crop
        c.undo(); c.crop = None
        blank = im.blank(200, 100, (255, 255, 255, 255)); blank[30:60, 50:120] = (0, 0, 200, 255)
        sc.restore(dict(base=blank, objects=[], counter_start=1)); c.selection = []
        c.crop_auto(); x, y, w, h = [round(v) for v in c.crop.rect()]
        check("auto-crop finds the content box", (x, y, w, h) == (50, 30, 70, 30), str((x, y, w, h)))
        # --- text: a plain click makes a square box that hugs the text as you type; Enter finishes
        sc.restore(dict(base=im.blank(600, 400, (230, 235, 240, 255)), objects=[], counter_start=1)); c.selection = []
        c.set_tool("text"); self.drag((200, 200), (200, 200))
        tt = [o for o in sc.objects if o.kind == "text"][-1]
        check("click makes a text box that is a SQUARE", abs(tt.rect()[2] - tt.rect()[3]) < 1 and tt.p["autosize"], str(tt.rect()))
        c._edit["view"].get_buffer().set_text("1")
        check("typing one character keeps it a square", abs(tt.rect()[2] - tt.rect()[3]) < 1, str(tt.rect()))
        w1 = tt.rect()[2]
        c._edit["view"].get_buffer().set_text("1 2 3 4 5 6")
        check("more text widens the box as you type", tt.rect()[2] > w1 * 2 and abs(tt.rect()[3] - tt.rect()[2]) > 5, str(tt.rect()))
        c._edit["view"].get_buffer().set_text("one\ntwo")
        h2 = tt.rect()[3]
        check("a second line makes it taller", h2 > 40, str(tt.rect()))
        class K: pass
        c._edit_key(None, Gdk.KEY_Return, 0, Gdk.ModifierType(0))
        check("Enter finishes editing", c._edit is None and tt.text == "one\ntwo")
        # dragged text box stays the size the user chose
        c.set_tool("text"); self.drag((300, 60), (480, 120)); t3 = [o for o in sc.objects if o.kind == "text"][-1]
        c._edit["view"].get_buffer().set_text("x"); c._finish_text_edit()
        check("a dragged text box keeps its fixed size", not t3.p["autosize"] and abs(t3.rect()[2] - 180) < 3, str(t3.rect()))
        # --- cursor object
        n = len(sc.objects)
        cur = c.add_cursor("arrow", at=(100, 100))
        check("insert mouse cursor adds a movable image object", len(sc.objects) == n + 1 and cur.kind == "image" and cur.p["cursor"])
        c.arrange("back"); check("cursor can be sent to back", sc.objects[0] is cur)
        c.arrange("front"); check("cursor can be brought to front", sc.objects[-1] is cur)
        out = c.export_array()
        check("cursor is drawn into the export", not (out[95:130, 95:130] == sc.base[95:130, 95:130]).all())
        cap = c.add_cursor(sprite=(np.full((20, 12, 4), 255, np.uint8), 40, 50))
        check("a captured cursor sprite is placed where it was", (round(cap.x1), round(cap.y1)) == (40, 50))
        # =========================================================== tool stays active (Greenshot)
        sc.restore(dict(base=im.blank(600, 400, (230, 235, 240, 255)), objects=[], counter_start=1)); c.selection = []
        c.set_zoom(1.0)
        c.set_tool("rect"); self.drag((50, 50), (120, 100))
        check("drawing tool STAYS active after drawing (no jump back to Select)", c.tool == "rect")
        self.drag((200, 50), (260, 100))
        rects = [o for o in sc.objects if o.kind == "rect"]
        check("a second object is drawn without re-selecting the tool", len(rects) == 2 and c.tool == "rect")
        o2 = rects[-1]; x2, y2 = o2.x2, o2.y2
        self.drag((x2, y2), (x2 + 30, y2 + 20))
        check("the selected object's handle still resizes while the tool is active",
              abs(o2.x2 - (x2 + 30)) < 2 and len([o for o in sc.objects if o.kind == "rect"]) == 2 and c.tool == "rect")
        c.set_tool("text"); self.drag((300, 200), (300, 200)); c._edit["view"].get_buffer().set_text("a"); c._finish_text_edit()
        check("the text tool stays active after typing", c.tool == "text")
        self.drag((300, 300), (300, 300)); c._edit["view"].get_buffer().set_text("b"); c._finish_text_edit()
        check("a second text box is created with a single click", len([o for o in sc.objects if o.kind == "text"]) == 2)
        c.set_tool("select")

        # =========================================================== right-click menu (Greenshot's object menu)
        sc.restore(dict(base=im.blank(600, 400, (230, 235, 240, 255)), objects=[], counter_start=1)); c.selection = []
        a_ = sc.add(M.Obj("rect", 20, 20, 120, 80)); b_ = sc.add(M.Obj("ellipse", 150, 20, 250, 80)); s_ = sc.add(M.Obj("step", 300, 20, 330, 50))
        lab = lambda: C.Canvas.menu_labels(c.context_menu_model())
        c.select([b_]); L = lab()
        check("middle object: all four layer options", all(x in L for x in ("Up to top", "Up one level", "Down to bottom", "Down one level")), str(L[:5]))
        check("menu has Duplicate selected element / Copy / Cut / Delete", all(x in L for x in ("Duplicate selected element", "Copy", "Cut", "Delete")))
        check("menu has the Expand capture and move outside submenu (4 sides)", all(f"Expand capture and move outside > {d}" in L for d in ("Top", "Right", "Bottom", "Left")))
        check("menu has Stretch > Width / Height", "Stretch > Width" in L and "Stretch > Height" in L)
        check("menu has Dock to edge submenu (4 sides)", all(f"Dock to edge > {d}" in L for d in ("Top", "Right", "Bottom", "Left")))
        check("no Reset size for a plain shape", "Reset size" not in L)
        c.select([s_]); L = lab()
        check("top object: no 'Up' options", "Up to top" not in L and "Up one level" not in L and "Down to bottom" in L)
        check("step label offers Reset size", "Reset size" in L)
        c.select([a_]); L = lab()
        check("bottom object: no 'Down' options", "Down to bottom" not in L and "Down one level" not in L and "Up to top" in L)
        c.select([]); check("nothing selected -> empty menu", c.context_menu_model().get_n_items() == 0)

        # the operations behind the menu
        c.select([b_]); c.snap_to_edge("left"); check("Dock to edge > Left", b_.rect()[0] == 0)
        c.snap_to_edge("bottom"); check("Dock to edge > Bottom", abs(b_.rect()[1] + b_.rect()[3] - 400) < 1e-6)
        c.fit_to_image("width"); check("Stretch > Width fills the picture width", b_.rect()[0] == 0 and b_.rect()[2] == 600)
        c.fit_to_image("height"); check("Stretch > Height fills the picture height", b_.rect()[1] == 0 and b_.rect()[3] == 400)
        before_size = sc.size; ax = a_.x1
        c.select([a_]); w_a = a_.rect()[2]
        c.push_out("right")
        check("Expand capture > Right grows the canvas by the object's width", sc.size == (before_size[0] + int(w_a), before_size[1]), str(sc.size))
        check("...and moves the object into the new space (touching the right edge)", abs(a_.rect()[0] + a_.rect()[2] - sc.size[0]) < 1)
        check("...other objects stay on the same picture content", abs(s_.x1 - 300) < 1)
        c.undo(); check("expand capture is one undo step", sc.size == before_size)
        c.select([s_]); s_.set_rect(300, 20, 90, 90); c.reset_size()
        check("Reset size restores a step label to 30x30", (round(s_.rect()[2]), round(s_.rect()[3])) == (30, 30))

        # =========================================================== the mouse cursor: move + layer order only
        sc.restore(dict(base=im.blank(600, 400, (230, 235, 240, 255)), objects=[], counter_start=1)); c.selection = []
        r_ = sc.add(M.Obj("rect", 10, 10, 60, 60))
        cur = c.add_cursor("arrow", at=(200, 200)); cx, cy, cw, ch = cur.rect()
        check("a cursor object has NO resize handles", M.handles(cur) == [] and M.handle_at(cur, cx + cw, cy + ch, 6) is None)
        c.set_tool("select"); c.select([cur])
        self.drag((cx + cw, cy + ch), (cx + cw + 40, cy + ch + 40))        # grab where a corner handle would be
        check("dragging a cursor's corner MOVES it, it never resizes", (round(cur.rect()[2]), round(cur.rect()[3])) == (round(cw), round(ch)) and cur.rect()[0] > cx + 30)
        L = C.Canvas.menu_labels(c.context_menu_model())
        check("cursor menu: layer order + Delete only", L and all(x in ("Up to top", "Up one level", "Down to bottom", "Down one level", "Delete") for x in L), str(L))
        c.arrange("back"); check("cursor can be sent backward", sc.objects[0] is cur)

        # =========================================================== Ctrl + wheel zoom
        c.set_zoom(1.0); c._pointer_override = (200.0, 150.0)
        check("Ctrl+wheel up zooms in", c.handle_ctrl_scroll(-1) and c.zoom > 1.0, str(c.zoom))
        z = c.zoom; c.handle_ctrl_scroll(1); check("Ctrl+wheel down zooms back out", c.zoom < z, str(c.zoom))
        c.set_zoom(1.0); c._scroll_accum = 0.0
        c.handle_ctrl_scroll(-0.4); c.handle_ctrl_scroll(-0.4); check("small trackpad scrolls accumulate (no zoom yet)", c.zoom == 1.0)
        c.handle_ctrl_scroll(-0.4); check("...and zoom once they add up to a full notch", c.zoom > 1.0)
        c.set_zoom(1.0); c.handle_ctrl_scroll(-1)
        check("one notch changes the zoom by 25%", abs(c.zoom - 1.25) < 1e-9, str(c.zoom))
        c._pointer_override = None

        # =========================================================== selection handles: small and OUTSIDE the object
        sc.restore(dict(base=im.blank(600, 400, (230, 235, 240, 255)), objects=[], counter_start=1)); c.selection = []
        r_ = sc.add(M.Obj("rect", 100, 100, 300, 260)); c.set_zoom(1.0); c.select([r_])
        pts = {n: (x, y) for n, x, y in c._handle_points(r_)}
        wx0, wy0 = c.to_widget(100, 100); wx1, wy1 = c.to_widget(300, 260)
        check("handle squares are 4 px", C.HANDLE * 2 == 4)
        check("corner handles sit outside the corners", pts["nw"][0] < wx0 and pts["nw"][1] < wy0 and pts["se"][0] > wx1 and pts["se"][1] > wy1)
        check("edge handles sit outside the edges", pts["n"][1] < wy0 and pts["s"][1] > wy1 and pts["w"][0] < wx0 and pts["e"][0] > wx1)
        hx, hy = pts["se"]
        check("a handle square never overlaps the object", hx - C.HANDLE > wx1 and hy - C.HANDLE > wy1 and pts["nw"][0] + C.HANDLE < wx0)
        check("the selection outline is drawn outside the object too", C.SELECT_GAP > 0)
        ix, iy = c.to_img(*pts["se"])
        check("a handle is grabbed where it is drawn", c._handle_at(r_, ix, iy) == "se")
        check("...and by clicking right at the object's corner", c._handle_at(r_, 300, 260) == "se")
        check("...but not from far away", c._handle_at(r_, 330, 290) is None)
        c.set_zoom(4.0)
        check("the grab area stays the same size in screen pixels when zoomed", c._handle_at(r_, 301, 261) == "se" and c._handle_at(r_, 303, 263) is None)
        c.set_zoom(1.0)
        ln = sc.add(M.Obj("line", 50, 300, 150, 340)); c.select([ln]); lp = {n: (x, y) for n, x, y in c._handle_points(ln)}
        check("line end handles stay centred on the end points", lp["start"] == c.to_widget(50, 300) and lp["end"] == c.to_widget(150, 340))
        print("\nFAILED" if fails else "\nALL PASSED", fails or "")
        self.quit(); sys.exit(1 if fails else 0)

app = App(application_id="local.snipshot.test")
app.run([])
