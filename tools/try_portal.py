import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk
Gtk.init()
import capture as C
loop = GLib.MainLoop()
t0 = time.time()
def done(arr, msg):
    if arr is None:
        print("NO IMAGE:", msg)
    else:
        h, w = arr.shape[:2]
        lay = C.monitor_layout()
        print(f"portal image: {w} x {h}  ({time.time()-t0:.1f}s)   monitor layout (logical): {lay}")
        print("scale info:", C.image_scale(w, h, lay))
    loop.quit()
C.portal_screenshot(done, interactive=False, timeout_s=25)
GLib.timeout_add_seconds(30, loop.quit)
loop.run()
