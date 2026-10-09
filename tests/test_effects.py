"""Tests for effects.py. Run:  python3 -I test_effects.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import effects as fx

fails = 0


def check(name, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", name, extra)


rng = np.random.default_rng(1)
noise = rng.integers(0, 256, (101, 157, 4), dtype=np.uint8)          # odd sizes on purpose

# ---- pixelate
for b in (2, 5, 8, 16, 33):
    p = fx.pixelate(noise, b)
    ok_shape = p.shape == noise.shape and p.dtype == np.uint8
    ys, xs = fx._starts(101, b), fx._starts(157, b)
    ye, xe = list(ys[1:]) + [101], list(xs[1:]) + [157]
    flat = True
    means_ok = True
    for y0, y1 in zip(ys, ye):
        for x0, x1 in zip(xs, xe):
            cell = p[y0:y1, x0:x1].reshape(-1, 4)
            src = noise[y0:y1, x0:x1].reshape(-1, 4)
            flat &= bool((cell == cell[0]).all())
            means_ok &= bool(np.abs(cell[0].astype(int) - src.mean(axis=0)).max() <= 0.5 + 1e-9)
    slivers = [e - s0 for s0, e in zip(ys, ye)] + [e - s0 for s0, e in zip(xs, xe)]
    check(f"pixelate block={b}: shape kept", ok_shape)
    check(f"pixelate block={b}: cells flat (cohesive grid)", flat)
    check(f"pixelate block={b}: cell colour == average of source cell", means_ok)
    check(f"pixelate block={b}: no sliver cells (smallest cell {min(slivers)}px)", min(slivers) * 2 >= b or b >= 101)

# cohesion is independent of region position: a region cut out of the middle still starts its grid at its own corner
sub = noise[17:80, 23:140]
a, b_ = fx.pixelate(sub, 10), fx.pixelate(noise[17:80, 23:140].copy(), 10)
check("pixelate is deterministic", (a == b_).all())
check("pixelate grid anchored at region top-left", (a[:10, :10] == a[0, 0]).all() and not (a[:10, 10:20] == a[0, 0]).all())

# pixel size really controls coarseness: number of distinct colours falls as the size grows
counts = [len({tuple(px) for px in fx.pixelate(noise, b).reshape(-1, 4)}) for b in (2, 4, 8, 16)]
check("coarser pixel size => fewer distinct colours", all(counts[i] > counts[i + 1] for i in range(3)), str(counts))

check("pixelate size 1 is a no-op copy", (fx.pixelate(noise, 1) == noise).all() and fx.pixelate(noise, 1) is not noise)
check("pixelate size larger than region clamps (single colour)", len({tuple(px) for px in fx.pixelate(noise[:8, :9], 500).reshape(-1, 4)}) == 1)
check("pixelate empty region ok", fx.pixelate(noise[:0], 5).shape[0] == 0)
check("pixelate does not modify input", (noise == np.random.default_rng(1).integers(0, 256, (101, 157, 4), dtype=np.uint8)).all())

r1, r2 = fx.pixelate(noise, 12, randomise=True, seed=7), fx.pixelate(noise, 12, randomise=True, seed=7)
r3 = fx.pixelate(noise, 12, randomise=True, seed=8)
check("randomised grid: same seed repeats, different seed differs", (r1 == r2).all() and not (r1 == r3).all())
check("randomised grid: shape kept", r1.shape == noise.shape)

# ---- blur
flat_img = np.full((40, 50, 4), 123, dtype=np.uint8)
check("blur of a flat image is unchanged", (fx.blur(flat_img, 9) == flat_img).all())
step = np.zeros((20, 60, 4), dtype=np.uint8)
step[:, 30:] = 255
bl = fx.blur(step, 5)[10, :, 0].astype(int)
check("blur of a hard edge is a smooth monotonic ramp", bool((np.diff(bl) >= 0).all()) and 0 < bl[26] < 255 and 0 < bl[34] < 255)
check("blur keeps the mean brightness", abs(fx.blur(noise, 6).mean() - noise.mean()) < 1.5)
var = [fx.blur(noise, r).astype(float).std() for r in (1, 3, 6, 12, 24)]
check("larger radius => smoother (variance falls)", all(var[i] > var[i + 1] for i in range(4)), str([round(v, 1) for v in var]))
check("blur radius 0 is a copy", (fx.blur(noise, 0) == noise).all())
check("blur shape/dtype kept", fx.blur(noise, 7).shape == noise.shape and fx.blur(noise, 7).dtype == np.uint8)

# blur_region reads the surroundings so the region's edge is not darkened by clamping
base = np.full((100, 100, 4), 200, dtype=np.uint8)
reg = fx.blur_region(base, 30, 30, 40, 40, 8)
check("blur_region edges blend with surroundings (no dark fringe)", reg.shape == (40, 40, 4) and (reg == 200).all())
edge = fx.blur_region(base, -10, -10, 50, 50, 8)
check("blur_region clips to the image", edge.shape == (40, 40, 4))
check("blur_region fully outside => empty", fx.blur_region(base, 500, 500, 10, 10, 5).size == 0)

# ---- speed (must stay interactive while a rectangle is being dragged)
big = rng.integers(0, 256, (800, 1200, 4), dtype=np.uint8)
t = time.perf_counter(); fx.pixelate(big, 12); tp = (time.perf_counter() - t) * 1000
t = time.perf_counter(); fx.blur(big, 30); tb = (time.perf_counter() - t) * 1000
check(f"pixelate 1200x800 fast enough ({tp:.0f} ms)", tp < 250)
check(f"blur radius 30 on 1200x800 fast enough ({tb:.0f} ms)", tb < 1500)

print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
