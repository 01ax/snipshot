"""Recording one WINDOW through the desktop's real ScreenCast portal picker, inside the PRIVATE headless session:

    tools/headless_session.sh python3 -I tests/test_record_window.py

The picker dialog is GNOME's own ("Share Screen"); the test clicks it with synthetic input."""
import glob
import os
import subprocess
import sys
import tempfile
import threading
import time

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("Refusing to run: start this with tools/headless_session.sh.")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
from gi.repository import GLib
import config as CFG
import recorder as R
import recording as REC
import remote_input

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


tmp = tempfile.mkdtemp(prefix="snipshot-win-")
cfg = CFG.Config(os.path.join(tmp, "config.json"))
cfg["record_dir"] = os.path.join(tmp, "videos")
sock = sorted(os.path.basename(p) for p in glob.glob(os.environ["XDG_RUNTIME_DIR"] + "/wayland-*") if not p.endswith(".lock"))[0]
procs = []
loop = GLib.MainLoop()
inp = None


def pattern(*args):
    p = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "tools", "test_pattern.py"), *args],
                         env=dict(os.environ, WAYLAND_DISPLAY=sock, GDK_BACKEND="wayland"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    time.sleep(2.5)
    return p


def run_job(pick, seconds=3.5):
    """Start a window recording; ``pick()`` runs in a thread once the picker is up (it clicks the dialog)."""
    res = {}
    job = REC.RecordingJob(cfg, {"kind": "window"}, system=False, mic=False, cursor=False,
                           on_done=lambda r: (res.update(r), loop.quit()))
    job.start()
    threading.Thread(target=lambda: (time.sleep(2.5), pick()), daemon=True).start()
    GLib.timeout_add(int((2.5 + seconds + 1.5) * 1000), lambda: (job.stop(), False)[1])
    GLib.timeout_add_seconds(45, loop.quit)
    loop.run()
    return job, res


def frames(path, n=200):
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    R.ensure_gst()
    pipe = Gst.parse_launch(f'filesrc location="{path}" ! decodebin ! videoconvert ! video/x-raw,format=RGB ! appsink name=s sync=false')
    s = pipe.get_by_name("s")
    pipe.set_state(Gst.State.PLAYING)
    out = []
    while len(out) < n:
        smp = s.emit("try-pull-sample", 2 * Gst.SECOND)
        if smp is None:
            break
        st = smp.get_caps().get_structure(0)
        w, h = st.get_value("width"), st.get_value("height")
        ok, info = smp.get_buffer().map(Gst.MapFlags.READ)
        out.append(np.frombuffer(info.data, np.uint8).reshape(h, info.size // h)[:, : w * 3].reshape(h, w, 3).copy())
        smp.get_buffer().unmap(info)
    pipe.set_state(Gst.State.NULL)
    return out


def near(px, rgb, tol=70):
    return all(abs(int(a) - b) <= tol for a, b in zip(px, rgb))


try:
    inp = remote_input.RemoteInput()

    def choose():
        inp.click(640, 271)          # the window's row in GNOME's "Share Screen" picker
        time.sleep(0.4)
        inp.click(927, 149)          # Share

    def cancel():
        inp.click(355, 149)

    def check_clip(res, label, w, h, expect_borders=None):
        info = R.probe_file(res["path"])
        v = info["video"][0] if info["video"] else None
        check(f"{label}: one video size, the window's own ({w}x{h}), not the 1280x720 screen",
              v is not None and len(info["video"]) == 1 and v[1:3] == (w, h), str(info["video"]))
        fr = frames(res["path"])
        check(f"{label}: about 3+ seconds of frames", len(fr) >= 60, str(len(fr)))
        return fr

    # 1. a window that is resized (same shape) while it is recorded
    pattern("--window", "640", "400", "--resize-to", "800", "500", "9.0")
    inp.move(640, 380); inp.move(650, 390)
    job, res = run_job(choose, seconds=5.0)
    check("window recording: finished without error", res.get("path") and not res.get("error"), str({k: v for k, v in res.items() if k != "notes"}))
    if res.get("path"):
        fr = check_clip(res, "window recording", 640, 400)
        for label, f in (("start", fr[5]), ("after the resize", fr[-5])):
            h, w = f.shape[:2]
            check(f"window recording ({label}): the window fills the frame, bars red | green | blue, no black canvas",
                  near(f[h // 3, int(w * 0.12)], (255, 0, 0)) and near(f[h // 3, w // 2], (0, 255, 0)) and near(f[h // 3, int(w * 0.88)], (0, 0, 255))
                  and near(f[h - 4, w - 4], (0, 0, 255)), str((f[h // 3, int(w * 0.12)], f[h // 3, w // 2], f[h // 3, int(w * 0.88)], f[h - 4, w - 4])))
    procs[-1].terminate()

    # 2. a window that changes SHAPE: scaled to fit with black borders, never stretched
    pattern("--window", "640", "400", "--resize-to", "800", "400", "9.0")
    inp.move(640, 380); inp.move(650, 390)
    job, res = run_job(choose, seconds=5.0)
    if res.get("path"):
        fr = check_clip(res, "wider window", 640, 400)
        f = fr[-5]
        h, w = f.shape[:2]
        check("wider window: letterboxed (black bars above and below), picture undistorted",
              near(f[3, w // 2], (0, 0, 0), 30) and near(f[h // 2, int(w * 0.12)], (255, 0, 0)) and near(f[h // 2, w // 2], (0, 255, 0)),
              str((f[3, w // 2], f[h // 2, int(w * 0.12)], f[h // 2, w // 2])))
    else:
        check("wider window recorded", False, str(res))
    procs[-1].terminate()

    # 3. a still window (no new frames are sent for it)
    pattern("--window", "640", "400", "--static")
    inp.move(640, 380); inp.move(650, 390)
    job, res = run_job(choose, seconds=3.5)
    if res.get("path"):
        fr = check_clip(res, "still window", 640, 400)
    else:
        check("still window recorded", False, str(res))
    procs[-1].terminate()

    # 4. cancel in the picker: no error, no file
    pattern("--window", "640", "400")
    inp.move(640, 380); inp.move(650, 390)
    before = set(glob.glob(os.path.join(cfg.record_folder, "*")))
    job, res = run_job(cancel, seconds=0.5)
    check("cancelling the picker is a quiet cancel (no error, no file)", res.get("cancelled") and not res.get("error") and not res.get("path")
          and set(glob.glob(os.path.join(cfg.record_folder, "*"))) == before, str({k: v for k, v in res.items() if k != "notes"}))
finally:
    if inp:
        inp.close()
    for p in procs:
        p.terminate()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
