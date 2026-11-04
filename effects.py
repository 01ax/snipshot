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


def _box_sum_valid(a, r, axis):
    """Sum over every window of 2r+1 along ``axis`` of an integer array, without padding (2r shorter along that axis)."""
    n = a.shape[axis] - 2 * r
    idx = lambda start, stop: tuple(slice(start, stop) if k == axis else slice(None) for k in range(a.ndim))
    if r <= 4:                                              # a few shifted additions
        out = a[idx(0, n)].copy()
        for k in range(1, 2 * r + 1):
            out += a[idx(k, k + n)]
        return out
    c = np.cumsum(a, axis=axis, dtype=a.dtype)              # a running sum, differenced, for wide windows
    out = c[idx(2 * r, 2 * r + n)].copy()
    out[idx(1, None)] -= c[idx(0, n - 1)]
    return out


def _box_sum_edge(a, r, axis):
    """Window sums of 2r+1 along ``axis`` of an integer array, edge pixels repeated beyond the border."""
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    return _box_sum_valid(np.pad(a, pad, mode="edge"), r, axis)


def blur(img, radius):
    """Greenshot-style blur: box blur, horizontal then vertical, twice. radius <= 0 returns a copy.

    Done in integers: four box blurs are an integer sum of at most 255 * norm, divided by norm = (2r+1)^4 (dividing at each
    step, as the float version did, only changes the scale, and the edge padding scales with it). Rounding once at the end
    gives exactly the float version's result, because norm is odd, so the quotient is never a rounding tie. About 3x faster."""
    radius = int(min(radius, MAX_BLUR_RADIUS))
    if radius <= 0 or img.size == 0:
        return np.ascontiguousarray(img).copy()
    norm = (2 * radius + 1) ** 4
    a = img.astype(np.int32 if 255 * norm < 2 ** 31 else np.int64)
    for _ in range(2):
        a = _box_sum_edge(a, radius, 1)
        a = _box_sum_edge(a, radius, 0)
    return ((2 * a + norm) // (2 * norm)).astype(np.uint8)


def blur_sparse(a, radius, tile=16, lut=None):
    """``blur(a[..., None], radius)[..., 0]`` for a 2-D uint8 array, but fast when most of it is flat.

    ``a`` is normally zero around its borders (a shadow's alpha plane, which is cut out with room to spare); if it is
    not, the plain blur is used. It is split into small tiles: a tile whose neighbourhood (the blur reaches 2 * radius pixels) is all one value stays that value
    (the blur of a constant is that constant), and only the other tiles, which lie along the outlines, are blurred, all
    at once. So the cost follows the outline, not the area: an outline rectangle covering the screen is blurred along
    its four edges instead of all of its millions of empty pixels. The result is identical to the plain blur.
    ``lut`` (256 uint8 values, ``lut[0] == 0``) is looked up on the result, again only where it matters."""
    radius = int(min(max(radius, 0), MAX_BLUR_RADIUS))
    h, w = a.shape
    if radius <= 0 or a.size == 0:
        return np.ascontiguousarray(a).copy()
    m = 2 * radius                                          # how far one pixel's blur reaches
    if a[:m].any() or a[-m:].any() or a[:, :m].any() or a[:, -m:].any():
        return blur(a[..., None], radius)[..., 0]           # not zero at the borders: the plain blur treats them specially
    T = max(int(tile), m)                                   # so that a tile's neighbourhood is only its direct neighbours
    th, tw = -(-h // T), -(-w // T)
    P = np.zeros((th * T + 2 * m, tw * T + 2 * m), np.uint8)
    P[m:m + h, m:m + w] = a
    rows = P[m:m + th * T, m:m + tw * T].reshape(th, T, tw * T)       # reduce whole rows first: 10x faster than 4-D
    lo = np.zeros((th + 2, tw + 2), np.uint8)
    hi = np.zeros((th + 2, tw + 2), np.uint8)
    lo[1:-1, 1:-1] = rows.min(axis=1).reshape(th, tw, T).min(axis=2)
    hi[1:-1, 1:-1] = rows.max(axis=1).reshape(th, tw, T).max(axis=2)
    nlo = np.minimum.reduce([lo[i:i + th, j:j + tw] for i in range(3) for j in range(3)])     # neighbourhood of each tile
    nhi = np.maximum.reduce([hi[i:i + th, j:j + tw] for i in range(3) for j in range(3)])
    out = np.zeros((th * T, tw * T), np.uint8)
    tiles = out.reshape(th, T, tw, T).transpose(0, 2, 1, 3)           # a (th, tw, T, T) view of ``out``
    flat = nlo == nhi
    vals = nlo if lut is None else lut[nlo]
    tiles[flat & (vals > 0)] = vals[flat & (vals > 0)][:, None, None]
    ys, xs = np.nonzero(~flat)
    W = T + 2 * m
    wins = np.lib.stride_tricks.sliding_window_view(P, (W, W))
    # Four box blurs of window 2r+1 are, before dividing, an integer sum of at most 255 * norm, divided by norm = (2r+1)^4.
    # Doing it in integers and rounding once is exactly what the float version gives: norm is odd, so the quotient is
    # never a rounding tie, and float error is far smaller than the distance to one.
    norm = (2 * radius + 1) ** 4
    dt = np.int32 if 255 * norm < 2 ** 31 else np.int64
    for k in range(0, len(ys), 2000):                                 # in chunks, to bound memory
        y, x = ys[k:k + 2000], xs[k:k + 2000]
        b = wins[y * T, x * T].astype(dt)                             # (n, W, W)
        for _ in range(2):
            b = _box_sum_valid(b, radius, 2)
            b = _box_sum_valid(b, radius, 1)
        b = ((2 * b + norm) // (2 * norm)).astype(np.uint8)           # b / norm, rounded (never exactly on a tie)
        tiles[y, x] = b if lut is None else lut[b]
    return np.ascontiguousarray(out[:h, :w])


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
