import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model as M, render as R
fails = 0
def check(n, ok, extra=""):
    global fails; fails += 0 if ok else 1; print(("PASS" if ok else "FAIL"), "-", n, extra)
o = M.Obj("text", 0, 0, 10, 10)
w0, h0 = R.fit_text_size(o, " ")
check("empty box is a square", w0 == h0, f"{w0}x{h0}")
w1, h1 = R.fit_text_size(o, "1")
check("a single character '1' gets a SQUARE", w1 == h1, f"{w1}x{h1}")
w2, h2 = R.fit_text_size(o, "Hello world")
check("longer text widens the box, height unchanged", w2 > w1 and h2 == h1, f"{w2}x{h2}")
w3, h3 = R.fit_text_size(o, "Hello\nworld")
check("two lines make it taller, width follows the longest line", h3 > h2 and abs(w3 - max(R.fit_text_size(o, "Hello")[0], R.fit_text_size(o, "world")[0])) <= 1, f"{w3}x{h3}")
o.p["font_size"] = 24
check("bigger font -> bigger box", R.fit_text_size(o, "1")[0] > w1)
o.p["font_size"] = 11; o.p["thickness"] = 6
check("thicker border -> more padding", R.fit_text_size(o, "1")[0] > w1)
print("\nFAILED" if fails else "\nALL PASSED", fails or ""); sys.exit(1 if fails else 0)
