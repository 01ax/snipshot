import os, sys, tempfile
os.environ["SNIPSHOT_CONFIG_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
from PIL import Image, ImageDraw
import app as A, imaging as im, picker as PK
class T(A.SnipshotApp):
    def apply_settings(self): pass
    def activate_command(self, args):
        self.hold()
        pil = Image.new("RGB", (900, 500), (40, 60, 110)); d = ImageDraw.Draw(pil); d.rectangle([60, 80, 840, 440], fill=(236, 240, 245))
        p = PK.Picker(im.from_pil(pil), lambda *a: None, "900 x 500"); p.present()
        def snap():
            w, h = p.get_width(), p.get_height()
            sn = Gtk.Snapshot(); Gtk.WidgetPaintable.new(p).snapshot(sn, w, h); node = sn.to_node()
            p.get_native().get_renderer().render_texture(node, None).save_to_png(sys.argv[1]); print("saved", w, h); self.quit(); return False
        GLib.timeout_add(900, snap)
T().run([sys.argv[0]])
