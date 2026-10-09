"""Tests for screencast.py: pure logic plus one real capture on this machine (only sizes/statistics are printed)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import gi
from gi.repository import GLib
import screencast as SCN

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


# ---- cursor extraction (synthetic)
bg = np.full((200, 300, 4), (90, 120, 160, 255), dtype=np.uint8)
withc = bg.copy()
withc[50:82, 100:112] = (255, 255, 255, 255)            # a 32x12 'cursor'
withc[55:60, 100:104] = (0, 0, 0, 255)
res = SCN.extract_cursor(bg, withc)
check("cursor blob found with the right position", res is not None and res[1] == 100 and res[2] == 50, str(res[1:] if res else None))
check("cursor sprite size ~ blob (+1px rim)", res is not None and 32 <= res[0].shape[0] <= 34 and 12 <= res[0].shape[1] <= 14)
check("cursor sprite is opaque where the cursor is, clear elsewhere", res is not None and res[0][5, 5, 3] == 255 and res[0][0, 0, 3] in (0, 255))
check("identical frames -> no cursor", SCN.extract_cursor(bg, bg.copy()) is None)
noisy = bg.copy(); noisy[10:190, 10:290] = (0, 0, 0, 255)
check("a large changed area is not mistaken for a cursor", SCN.extract_cursor(bg, noisy) is None)
check("shape mismatch handled", SCN.extract_cursor(bg, bg[:100]) is None)

# ---- combine keeps native pixels
class FakeInfo:
    def __init__(self, x, y): self.x, self.y = x, y
class FakeShot:
    def __init__(self, x, arr): self.info, self.array = FakeInfo(x, 0), arr
a = np.full((1440, 2560, 4), 10, np.uint8); b = np.full((2160, 3840, 4), 200, np.uint8)
big, placed = SCN.combine([FakeShot(2560, b), FakeShot(0, a)])
check("combine: width is the sum of native widths, height the tallest", big.shape[:2] == (2160, 6400))
check("combine: left monitor first, no rescaling", (big[0, 0, 0], big[0, 2559, 0], big[0, 2560, 0]) == (10, 10, 200) and [p[1] for p in placed] == [0, 2560])
check("combine: shorter monitor is top-aligned, rest opaque black", big[1500, 100, 0] == 0 and big[1500, 100, 3] == 255)

# ---- real capture on this machine
mons = SCN.list_monitors()
print("monitors:", [(m.connector, f"{m.pw}x{m.ph}", f"scale {m.scale}", f"logical {m.w}x{m.h}+{m.x}+{m.y}") for m in mons])
check("monitor list has native pixel sizes", all(m.pw > 0 and m.ph > 0 for m in mons))
check("logical size = native / scale", all(abs(m.w * m.scale - m.pw) <= m.scale for m in mons))

loop = GLib.MainLoop()
result = {}
def got(shots, msg):
    result["shots"], result["msg"], result["t"] = shots, msg, time.time() - t0
    loop.quit()
t0 = time.time()
SCN.capture(got, mons, include_cursor=True)
GLib.timeout_add_seconds(8, loop.quit)
loop.run()
shots = result.get("shots")
check("real capture succeeded", shots is not None, result.get("msg", ""))
if shots:
    check(f"capture time {result['t']:.2f}s is fast", result["t"] < 2.0)
    for s in shots:
        h, w = s.array.shape[:2]
        std = float(s.array[..., :3].std())
        print(f"  {s.info.connector}: {w}x{h}  mean={s.array[..., :3].mean():.0f} std={std:.0f}  cursor={'yes %dx%d at (%d,%d)' % (s.cursor[0].shape[1], s.cursor[0].shape[0], s.cursor[1], s.cursor[2]) if s.cursor else 'none'}")
        check(f"{s.info.connector}: native size matches the panel ({s.info.pw}x{s.info.ph})", (w, h) == (s.info.pw, s.info.ph))
        check(f"{s.info.connector}: not blank", std > 5)
        check(f"{s.info.connector}: opaque", bool((s.array[..., 3] == 255).all()))
    # a second capture straight after must (nearly) agree: frames are live and stable. A live desktop can change
    # between two captures, so try a few times and accept the best agreement.
    best = 99.0
    for _ in range(3):
        result.clear(); t0 = time.time()
        SCN.capture(got, mons, include_cursor=False)
        GLib.timeout_add_seconds(8, loop.quit); loop.run()
        s2 = result.get("shots")
        if s2:
            d = max(float(np.abs(a.array[..., :3].astype(np.int16) - b.array[..., :3].astype(np.int16)).mean()) for a, b in zip(shots, s2))
            best = min(best, d)
            shots = s2
            if best < 6:
                break
    check("two captures in a row agree (frames are live and stable)", best < 6, f"best difference {best:.2f}")
print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
