"""The real app's text (OCR) mode, driven like the shortcut drives it, inside the PRIVATE headless session:

    tools/headless_session.sh python3 -I tests/test_app_ocr.py

Needs Tesseract (skipped otherwise): `snipshot ocr` -> drag over rendered text -> the text is on the clipboard."""
import ast
import glob
import os
import re
import subprocess
import sys
import tempfile
import time

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("Refusing to run: start this with tools/headless_session.sh.")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import config as CFG
import ocr
import remote_input

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


if not ocr.available():
    print("SKIP - Tesseract is not installed (sudo apt install tesseract-ocr)")
    print("\nALL PASSED")
    sys.exit(0)

TEXT = "Snipshot reads this line 2026"
tmp = tempfile.mkdtemp(prefix="snipshot-ocr-e2e-")
cfgdir = os.path.join(tmp, "cfg")
os.makedirs(cfgdir)
CFG.Config(os.path.join(cfgdir, "config.json")).save()
env = dict(os.environ, SNIPSHOT_CONFIG_DIR=cfgdir, SNIPSHOT_DEBUG="1", SNIPSHOT_CHANNEL="dev")
logpath = os.path.join(tmp, "app.log")
logf = open(logpath, "w")
APP = [sys.executable, os.path.join(ROOT, "app.py")]
procs = []


def cmd(*args, wait=True, extra_env=None):
    p = subprocess.Popen(APP + list(args), env=dict(env, **(extra_env or {})), cwd=tmp, stdout=logf, stderr=logf)
    if wait:
        p.wait(20)
    return p


def log():
    return open(logpath).read()


def wait_log(pattern, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        m = re.search(pattern, log())
        if m:
            return m
        time.sleep(0.3)
    return None


def clipboard():
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "read_clipboard.py")], capture_output=True, text=True, timeout=30,
                       env=dict(os.environ, GDK_BACKEND="wayland"))
    out = r.stdout.strip().splitlines()
    if not out:
        print("   (reader printed nothing; stderr tail:", (r.stderr.strip().splitlines() or ["-"])[-1][:160], ")", flush=True)
    return ast.literal_eval(out[-1]) if out else None


def norm(s):
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


try:
    sock = sorted(os.path.basename(p) for p in glob.glob(os.environ["XDG_RUNTIME_DIR"] + "/wayland-*") if not p.endswith(".lock"))[0]
    pattern = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "tools", "test_pattern.py"), "--text", TEXT],
                               env=dict(os.environ, WAYLAND_DISPLAY=sock, GDK_BACKEND="wayland"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(pattern)
    time.sleep(2.5)
    daemon = cmd("--daemon", wait=False)
    procs.append(daemon)
    time.sleep(4)
    inp = remote_input.RemoteInput()

    # 1. drag over the text
    cmd("ocr")
    time.sleep(3.0)
    inp.move(640, 380); inp.move(650, 390)
    inp.drag((60, 90), (1240, 200))
    m = wait_log(r"ocr: showing (\d+) characters: (.*)")
    check("a window shows the recognised text", m is not None, log()[-400:] if not m else m.group(0))
    if m:
        check("the text is the text on the screen", norm(m.group(2)) == norm(TEXT), m.group(2))
    time.sleep(1.5)
    clip = clipboard()
    check("the text is on the clipboard", norm(clip) == norm(TEXT), repr(clip))

    # 2. an area with no text
    cmd("ocr")
    time.sleep(3.0)
    inp.move(640, 500); inp.move(650, 510)
    inp.drag((100, 400), (500, 600))
    check("a blank area says so instead of copying nothing", wait_log(r"notify: No text was found in that area") is not None, log()[-300:])

    # 3. Tesseract missing: a clear message with the install command
    daemon.terminate(); daemon.wait(10)
    daemon = cmd("--daemon", wait=False, extra_env={"SNIPSHOT_TESSERACT": "/nonexistent/tesseract"})
    procs.append(daemon)
    time.sleep(4)
    cmd("ocr", extra_env={"SNIPSHOT_TESSERACT": "/nonexistent/tesseract"})
    time.sleep(3.0)
    inp.move(640, 380); inp.move(650, 390)
    inp.drag((60, 90), (1240, 200))
    check("without Tesseract the notification gives the install command", wait_log(r"notify: Text recognition needs Tesseract\. Install it with:  sudo apt install tesseract-ocr") is not None, log()[-300:])
    inp.close()
finally:
    for p in procs:
        if p.poll() is None:
            p.terminate()
    if fails:
        print("---- app log ----\n" + log()[-2500:])
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
