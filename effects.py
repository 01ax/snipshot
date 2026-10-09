"""Obfuscation effects for Snipshot: pixelate and blur.

Pure NumPy, no GUI imports, so it can be tested on its own.

Pixelate  Every block of ``block`` x ``block`` pixels becomes the *average colour* of that block. The grid is
          regular and anchored at the top-left of the region, so the result is a clean mosaic whose coarseness
          is exactly the pixel size you chose. (Flameshot's default instead invents pixels from the region's
          surroundings plus noise, which looks random and ignores the size; this is the opposite.)
          Optionally the grid can be randomised, which is harder to reverse but looks less tidy.
Blur      Greenshot's approach: a box blur run twice in each direction, which approximates a Gaussian.
          Implemented with cumulative sums, so the cost does not grow with the radius.

All functions take and return ``H x W x C`` uint8 arrays (any channel order, any C) and never modify the input.
"""
import numpy as np

MAX_PIXEL_SIZE = 200
MAX_BLUR_RADIUS = 100


def _starts(length, block, rng=None, jitter=0):
    """Start index of each block along one axis. A leftover sliver at the end (under half a block) is
    merged into the previous block, so the grid never ends in a thin strip."""
    if rng is None or jitter <= 0:
        out = list(range(0, length, block))
    else:
        out, pos = [0], 0
        while True:
            pos += max(2, block + int(rng.integers(-jitter, jitter + 1)))
            if pos >= length:
                break
            out.append(pos)
    if len(out) > 1 and (length - out[-1]) * 2 < block:
        out.pop()
    return np.array(out)


def _mosaic(img, ys, xs):
    """Replace each cell of the grid (given by row starts ys, column starts xs) by its mean colour."""
    h, w = img.shape[:2]
    hs = np.diff(np.append(ys, h))
    ws = np.diff(np.append(xs, w))
    sums = np.add.reduceat(np.add.reduceat(img, ys, axis=0, dtype=np.uint64), xs, axis=1)
    counts = (hs[:, None] * ws[None, :])[..., None].astype(np.uint64)
    mean = ((sums + counts // 2) // counts).astype(np.uint8)       # rounded, not truncated
    return np.repeat(np.repeat(mean, hs, axis=0), ws, axis=1)


def pixelate(img, block, randomise=False, seed=None):
    """Mosaic of block x block average-colour cells. ``block`` <= 1 returns an unchanged copy."""
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return img.copy()
    block = int(max(1, min(block, MAX_PIXEL_SIZE, h, w)))
    if block <= 1:
        return img.copy()
    if not randomise:
        return _mosaic(img, _starts(h, block), _starts(w, block))
    # Randomised grid, in the style of Greenshot's newest versions: every row band gets its own column cuts.
    rng = np.random.default_rng(seed)
    jitter = max(1, block // 3)
    out = np.empty_like(img)
    ys = _starts(h, block, rng, jitter)
    for i, y0 in enumerate(ys):
        y1 = ys[i + 1] if i + 1 < len(ys) else h
        band = img[y0:y1]
        out[y0:y1] = _mosaic(band, np.array([0]), _starts(w, block, rng, jitter))
    return out


def _box_blur_axis(a, r, axis):
    """Box blur of radius r (window 2r+1) along one axis, edge pixels repeated beyond the border."""
    if r <= 0:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(p, axis=axis, dtype=np.float64)
    zero_shape = list(c.shape)
    zero_shape[axis] = 1
    c = np.concatenate([np.zeros(zero_shape), c], axis=axis)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / (2 * r + 1)


def blur(img, radius):
    """Greenshot-style blur: box blur, horizontal then vertical, twice. radius <= 0 returns a copy."""
    radius = int(min(radius, MAX_BLUR_RADIUS))
    if radius <= 0 or img.size == 0:
        return np.ascontiguousarray(img).copy()
    a = img.astype(np.float64)
    for _ in range(2):
        a = _box_blur_axis(a, radius, 1)
        a = _box_blur_axis(a, radius, 0)
    return np.clip(np.rint(a), 0, 255).astype(np.uint8)


def blur_margin(radius):
    """How many pixels around a region the blur reads: two passes, each reaching ``radius`` pixels."""
    return 2 * int(min(max(radius, 0), MAX_BLUR_RADIUS))


def blur_region(base, x, y, w, h, radius):
    """Blur the (x, y, w, h) region of ``base`` using the pixels around it too, so the edges blend in
    instead of fading towards the border colour. Returns just the blurred region (h x w x C)."""
    H, W = base.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((0, 0, base.shape[2]), dtype=base.dtype)
    m = blur_margin(radius)
    px0, py0, px1, py1 = max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m)
    out = blur(base[py0:py1, px0:px1], radius)
    return out[y0 - py0:y1 - py0, x0 - px0:x1 - px0]
