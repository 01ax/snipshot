"""OCR: render known text like a screen would show it (small, dark theme...), recognise it, compare.
Skipped (not failed) when Tesseract is not installed."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import ocr

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


def norm(s):
    return re.sub(r"\s+", " ", s.lower()).strip()


def render(lines, size, fg, bg, pad=10):
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    w = max(int(font.getlength(ln)) for ln in lines) + 2 * pad
    h = int(size * 1.5) * len(lines) + 2 * pad
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        d.text((pad, pad + i * int(size * 1.5)), ln, font=font, fill=fg)
    rgb = np.asarray(img)
    bgra = np.dstack([rgb[..., 2], rgb[..., 1], rgb[..., 0], np.full(rgb.shape[:2], 255, np.uint8)])
    return np.ascontiguousarray(bgra)


small = render(["Hello"], 14, (0, 0, 0), (255, 255, 255))
p = ocr.prepare(small)
check("prepare enlarges small text", p.width > small.shape[1] * 2 and p.mode == "L", f"{small.shape[1]}x{small.shape[0]} -> {p.width}x{p.height}")
dark = render(["Hello"], 14, (230, 230, 230), (30, 30, 36))
pd = np.asarray(ocr.prepare(dark))
check("prepare inverts a dark theme to dark-on-light", pd.mean() > 200, f"mean {pd.mean():.0f}")
check("clean(): trims, drops form feeds, collapses blank lines", ocr.clean("a  \n\n\n\nb\x0c\n") == "a\n\nb")

if not ocr.available():
    print("SKIP - Tesseract is not installed (sudo apt install tesseract-ocr); recognition checks not run")
    print("\nFAILED" if fails else "\nALL PASSED", fails or "")
    sys.exit(1 if fails else 0)

print("languages:", ocr.languages())
check("english is installed", "eng" in ocr.languages())
text = ["Snipshot copies this text", "to the clipboard 12345", "Error: connection refused (203.0.113.5)"]
for label, size, fg, bg in (("normal 18px", 18, (0, 0, 0), (255, 255, 255)), ("small 12px", 12, (20, 20, 20), (245, 245, 245)),
                            ("dark theme 14px", 14, (225, 225, 225), (30, 30, 36)), ("big 36px", 36, (10, 10, 10), (255, 255, 255))):
    got, err = ocr.recognize(render(text, size, fg, bg))
    want = norm(" ".join(text))
    ok = err is None and norm(got) == want
    check(f"reads {label} text exactly", ok, f"{err or repr(got)}" if not ok else "")

got, err = ocr.recognize(render(["Name"], 16, (0, 0, 0), (255, 255, 255)))
check("a single word is found", err is None and norm(got) == "name", repr(got))
blank = np.full((60, 200, 4), 255, np.uint8)
got, err = ocr.recognize(blank)
check("a blank area gives empty text, not an error", got == "" and err is None, f"{got!r} {err}")
got, err = ocr.recognize(render(["hola"], 20, (0, 0, 0), (255, 255, 255)), lang="zzz")
check("an uninstalled language is explained", got == "" and err and "zzz" in err and "not installed" in err, str(err))
tmp_left = [f for f in os.listdir(os.environ.get("TMPDIR", "/tmp")) if f.startswith("snipshot-ocr-")]
check("no temporary picture files are left behind", not tmp_left, str(tmp_left))
os.environ["SNIPSHOT_TESSERACT"] = "/nonexistent/tesseract"
got, err = ocr.recognize(small)
check("missing Tesseract gives the install hint", err == ocr.INSTALL_HINT and not ocr.available(), str(err))

print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
