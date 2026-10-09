"""The real app, driven the way the shortcut drives it, inside the PRIVATE headless session:

    tools/headless_session.sh python3 -I tests/test_app_record.py [screenshots-dir]

daemon + `snipshot record` -> overlay -> drag a region -> Enter -> countdown -> recording (tray turns red) ->
`snipshot record` again -> file saved. Also `record screen`, `record stop` and quitting while recording."""
import glob
import os
import subprocess
import sys
import tempfile
import time

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("Refusing to run: start this with tools/headless_session.sh.")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
from gi.repository import Gio, GLib
import config as CFG
import recorder as R
import remote_input

SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


tmp = tempfile.mkdtemp(prefix="snipshot-e2e-")
cfgdir, videos = os.path.join(tmp, "cfg"), os.path.join(tmp, "videos")
os.makedirs(cfgdir)
cfg = CFG.Config(os.path.join(cfgdir, "config.json"))
cfg["record_dir"], cfg["record_countdown"] = videos, 1
cfg["record_system_audio"], cfg["record_mic"] = False, False
cfg["output_dir"] = os.path.join(tmp, "pics")
cfg.save()
env = dict(os.environ, SNIPSHOT_CONFIG_DIR=cfgdir, SNIPSHOT_DEBUG="1", SNIPSHOT_CHANNEL="dev")
APP = [sys.executable, os.path.join(ROOT, "app.py")]
logf = open(os.path.join(tmp, "app.log"), "w")
procs = []


def cmd(*args, wait=True):
    p = subprocess.Popen(APP + list(args), env=env, cwd=tmp, stdout=logf, stderr=logf)
    if wait:
        p.wait(20)
    return p


bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)


def dget(dest, path, iface, prop):
    return bus.call_sync(dest, path, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (iface, prop)), None,
                         Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]


def tray_name():
    items = dget("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher", "RegisteredStatusNotifierItems")
    return items[0] if items else None


def tray_icon():
    n = tray_name()
    return dget(n, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "IconName") if n else None


def tray_labels():
    n = tray_name()
    r = bus.call_sync(n, "/MenuBar", "com.canonical.dbusmenu", "GetLayout", GLib.Variant("(iias)", (0, -1, [])), None,
                      Gio.DBusCallFlags.NONE, 3000, None).unpack()
    return [k[1].get("label") for k in r[1][2]]


def wait_for(fn, timeout=10, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = fn()
        except GLib.Error:
            v = None
        if v:
            return v
        time.sleep(step)
    return None


def grab(name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "grab_png.py"), os.path.join(SHOTS, name)], timeout=30, check=False)


def frame(path, index=8):
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    R.ensure_gst()
    pipe = Gst.parse_launch(f'filesrc location="{path}" ! decodebin ! videoconvert ! video/x-raw,format=RGB ! appsink name=s sync=false')
    s = pipe.get_by_name("s")
    pipe.set_state(Gst.State.PLAYING)
    out = None
    for _ in range(index + 1):
        smp = s.emit("try-pull-sample", 3 * Gst.SECOND)
        if smp is None:
            break
        st = smp.get_caps().get_structure(0)
        w, h = st.get_value("width"), st.get_value("height")
        ok, info = smp.get_buffer().map(Gst.MapFlags.READ)
        out = np.frombuffer(info.data, np.uint8).reshape(h, info.size // h)[:, : w * 3].reshape(h, w, 3).copy()
        smp.get_buffer().unmap(info)
    pipe.set_state(Gst.State.NULL)
    return out


def near(px, rgb, tol=70):
    return all(abs(int(a) - b) <= tol for a, b in zip(px, rgb))


def videos_list():
    return sorted(glob.glob(os.path.join(videos, "*.mp4")))


try:
    sock = sorted(os.path.basename(p) for p in glob.glob(os.environ["XDG_RUNTIME_DIR"] + "/wayland-*") if not p.endswith(".lock"))[0]
    pattern = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "tools", "test_pattern.py")],
                               env=dict(os.environ, WAYLAND_DISPLAY=sock, GDK_BACKEND="wayland"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(pattern)
    time.sleep(2.5)
    daemon = cmd("--daemon", wait=False)
    procs.append(daemon)
    check("tray icon registers", wait_for(tray_name, 15) is not None)
    check("tray starts with the normal icon", tray_icon() == "snipshot", str(tray_icon()))
    labels = tray_labels()
    check("tray menu offers recording", "Record region or window..." in labels and "Record full screen" in labels and "Open last recording" in labels, str(labels))

    inp = remote_input.RemoteInput()

    # ---- overlay in record mode, drag a region, Enter
    cmd("record")
    time.sleep(3.0)
    grab("e2e-overlay")
    inp.move(640, 380); inp.move(650, 390)
    inp.key("a")                                                        # turn system sound ON for this recording
    inp.drag((200, 150), (700, 500))
    grab("e2e-armed")
    inp.key("Return")
    during = tray_icon()
    ok = wait_for(lambda: tray_icon() == "snipshot-recording", 8)
    t_rec_start = time.time()
    check("after the countdown the tray icon turns red", ok, str(tray_icon()))
    labels = tray_labels()
    check("the tray icon is NOT red while only counting down", during == "snipshot", str(during))
    check("tray offers 'Stop recording (mm:ss)' first", labels and labels[0] and labels[0].startswith("Stop recording"), str(labels[:2]))
    check("while recording the tray menu offers Pause", "Pause recording" in labels, str(labels[:3]))
    time.sleep(1.5)
    labels = tray_labels()
    check("the timer in the tray menu advances", labels[0] not in ("Stop recording (00:00)",), str(labels[0]))
    t_pause = time.time()
    cmd("record", "pause")
    check("`record pause` turns the tray icon amber", wait_for(lambda: tray_icon() == "snipshot-paused", 5) is not None, str(tray_icon()))
    labels = tray_labels()
    check("paused: the menu says Resume and the stop entry says paused", "Resume recording" in labels and "paused" in labels[0], str(labels[:3]))
    time.sleep(2.5)
    cmd("record", "resume")
    check("`record resume` goes back to red", wait_for(lambda: tray_icon() == "snipshot-recording", 5) is not None, str(tray_icon()))
    paused_for = time.time() - t_pause
    cmd("record", "resume")                                             # resuming when already recording changes nothing
    time.sleep(1.5)
    check("resume when not paused is harmless", tray_icon() == "snipshot-recording")
    t_stop = time.time()
    cmd("record")                                                       # the same shortcut stops it
    got = wait_for(videos_list, 12)
    check("`record` again stops and saves a file", bool(got), str(got))
    check("tray icon goes back to normal", wait_for(lambda: tray_icon() == "snipshot", 6) is not None)
    if got:
        info = R.probe_file(got[0])
        check("the file is the dragged region at real pixels (500 x 350)", info["video"] and info["video"][0][1:3] == (500, 350), str(info["video"]))
        wall = t_stop - t_rec_start
        check("the paused time is not in the file (run ~%.1f s, paused ~%.1f s)" % (wall, paused_for),
              abs(info["duration"] - (wall - paused_for)) < 1.3, f"file {info['duration']:.2f}s, expected about {wall - paused_for:.2f}s")
        check("system sound was switched on, so the file has an audio stream", len(info["audio"]) == 1, str(info["audio"]))
        f = frame(got[0])
        # region x 200..700 of a screen whose red | green boundary is at x = 427: red on the left, green on the right
        check("picture matches the screen under the region (red | green)", f is not None and near(f[100, 100], (255, 0, 0)) and near(f[100, 400], (0, 255, 0)),
              str(f is not None and (f[100, 100], f[100, 400])))
    saved = open(os.path.join(tmp, "app.log")).read()
    check("a 'Recording saved' notification was raised", "Recording saved" in saved)
    saved_cfg = CFG.Config(os.path.join(cfgdir, "config.json"))
    check("the sound choice was remembered for next time", saved_cfg["record_system_audio"] is True and saved_cfg["record_mic"] is False)
    check("the tray remembers the last recording", saved_cfg["last_recording"].endswith(".mp4"), saved_cfg["last_recording"])

    # ---- record screen, then stop with `record stop`
    n_before = len(videos_list())
    cmd("record", "screen", "--audio", "none", "--delay", "0")
    check("record screen starts without a countdown", wait_for(lambda: tray_icon() == "snipshot-recording", 8) is not None)
    time.sleep(2.5)
    cmd("record", "stop")
    got = wait_for(lambda: len(videos_list()) > n_before, 12)
    check("`record stop` saves the whole-screen recording", bool(got))
    if got:
        info = R.probe_file(videos_list()[-1])
        check("whole screen is 1280 x 720", info["video"] and info["video"][0][1:3] == (1280, 720), str(info["video"]))

    # ---- quitting while recording saves the file first
    n_before = len(videos_list())
    cmd("record", "screen", "--audio", "none", "--delay", "0")
    wait_for(lambda: tray_icon() == "snipshot-recording", 8)
    time.sleep(2.0)
    q = cmd("--quit", wait=False)
    code = None
    try:
        daemon.wait(25)
        code = daemon.returncode
    except subprocess.TimeoutExpired:
        pass
    check("quit while recording: the app exits", code is not None, str(code))
    check("quit while recording: the recording was saved first", len(videos_list()) == n_before + 1, str(len(videos_list())))
    leftovers = glob.glob(os.path.join(videos, "*.part"))
    check("no .part files left", not leftovers, str(leftovers))
    inp.close()
finally:
    for p in procs:
        if p.poll() is None:
            p.terminate()
    log = open(os.path.join(tmp, "app.log")).read()
    if fails:
        print("---- app log ----\n" + log[-3000:])
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
