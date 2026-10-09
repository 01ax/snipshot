"""The post-capture preview: shown small, but built from real pixels (never softened by being enlarged again)."""
import os
import sys
import tempfile

os.environ["SNIPSHOT_CONFIG_DIR"] = tempfile.mkdtemp(prefix="snipshot-pt-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import picker as PK

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


L = PK.logical_size
check("a big capture is shown scaled down to fit, keeping its shape", L(2560, 1440) == (440, 248) and L(1000, 2000) == (135, 270), f"{L(2560, 1440)} {L(1000, 2000)}")
check("a small capture is never enlarged", L(200, 100) == (200, 100) and L(1, 1) == (1, 1))
P = PK.Thumb.physical_size
check("1x screen: the preview has exactly its on-screen pixel size", P(2560, 1440, 440, 248, 1) == (440, 248), str(P(2560, 1440, 440, 248, 1)))
check("2x screen (also what a 1.5x screen reports): twice the pixels, so it is crisp", P(2560, 1440, 440, 248, 2) == (880, 496) or P(2560, 1440, 440, 248, 2) == (880, 495), str(P(2560, 1440, 440, 248, 2)))
check("never more pixels than the capture itself has", P(300, 200, 300, 200, 2) == (300, 200) and P(100, 50, 100, 50, 3) == (100, 50))
check("shape is kept at every scale", all(abs(P(2560, 1440, 440, 248, s)[0] / P(2560, 1440, 440, 248, s)[1] - 2560 / 1440) < 0.02 for s in (1, 2, 3)))
arr = np.zeros((1440, 2560, 4), np.uint8)
arr[..., 3] = 255
t = PK.Thumb(arr)
check("the preview widget reports its logical size to the layout", t.measure(0, -1)[1] == 440 and t.measure(1, -1)[1] == 248, str((t.measure(0, -1)[1], t.measure(1, -1)[1])))
check("its texture for 2x has twice the pixels of the one for 1x", t.texture(2).get_width() == 2 * t.texture(1).get_width() or abs(t.texture(2).get_width() - 2 * t.texture(1).get_width()) <= 1,
      f"{t.texture(1).get_width()} vs {t.texture(2).get_width()}")
print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
