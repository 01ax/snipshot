"""Save what the (private headless) desktop shows as PNG files, one per monitor: grab_png.py OUT_PREFIX.
Used to look at the overlay in tests; refuses to run outside tools/headless_session.sh."""
import os
import sys

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("grab_png only runs inside tools/headless_session.sh")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gi.repository import GLib
from PIL import Image
import screencast

loop = GLib.MainLoop()


def done(shots, msg):
    for i, s in enumerate(shots or []):
        a = s.array[..., [2, 1, 0]]                       # BGRA -> RGB
        Image.fromarray(a).save(f"{sys.argv[1]}-{i}.png")
    if not shots:
        print("grab failed:", msg, file=sys.stderr)
    loop.quit()


screencast.capture(done, include_cursor=False)
GLib.timeout_add_seconds(8, loop.quit)
loop.run()
