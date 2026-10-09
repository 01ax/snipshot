"""End-to-end recording test against a PRIVATE headless GNOME session (never the real desktop):

    tools/headless_session.sh python3 -I tests/test_record_session.py

Records a known test-pattern window through Mutter's real ScreenCast + PipeWire path, with tones played into the
virtual speakers and virtual microphone, and checks the file: size, duration, frame count, picture content, region
crop, and which audio tones ended up in the mix."""
import glob
import os
import subprocess
import sys
import tempfile
import time

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("Refusing to run: this test must be started with tools/headless_session.sh so it never records a real screen.")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import GLib, Gst, GstApp  # noqa: E402,F401
import castsession
import recorder as R
import screencast

HERE = os.path.dirname(os.path.abspath(__file__))
fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


R.ensure_gst()
loop = GLib.MainLoop()
tmp = tempfile.mkdtemp(prefix="snipshot-rs-")
sink, mic_feed = os.environ["VIRTUAL_SINK"], os.environ["VIRTUAL_MIC_FEED"]
procs = []


def spawn(cmd, env=None):
    p = subprocess.Popen(cmd, env=env or os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    return p


def wait_loop(ms):
    GLib.timeout_add(ms, lambda: (loop.quit(), False)[1])
    loop.run()


def start_pattern(static=False):
    sock = sorted(os.path.basename(p) for p in glob.glob(os.path.join(os.environ["XDG_RUNTIME_DIR"], "wayland-*"))
                  if not p.endswith(".lock"))
    env = dict(os.environ, WAYLAND_DISPLAY=sock[0], GDK_BACKEND="wayland")
    p = spawn([sys.executable, "-I", os.path.join(os.path.dirname(HERE), "tools", "test_pattern.py")] + (["--static"] if static else []), env)
    wait_loop(2500)
    return p


def tone(device, freq):
    return spawn(["gst-launch-1.0", "-q", "audiotestsrc", "is-live=true", f"freq={freq}", "volume=0.3", "!",
                  "audioconvert", "!", "audioresample", "!", "pulsesink", f"device={device}"])


def record(name, fmt, audio, crop=None, seconds=3.0, cursor=False, fps=30):
    """Record the virtual monitor; returns (path or None, error, mon size)."""
    mons = screencast.list_monitors()
    m = mons[0]
    out = os.path.join(tmp, name)
    res = {}
    cast = castsession.MonitorCast(m.connector, cursor=cursor, size=(m.pw, m.ph))
    rec_holder = {}

    def got_node(info, err):
        if err:
            res["err"] = err
            loop.quit()
            return
        video = {"kind": "pipewire", "node": info["node"], "size": info["size"], "crop": crop}
        rec = R.Recorder(video, audio, out, fmt, fps, "medium", on_done=lambda p, e: (res.update(path=p, err=e), loop.quit()))
        rec_holder["rec"] = rec
        rec.start()
        if rec.state == "recording":
            GLib.timeout_add(int(seconds * 1000), lambda: (rec.stop(), False)[1])

    cast.open(got_node)
    guard = GLib.timeout_add_seconds(int(seconds) + 20, loop.quit)
    loop.run()
    if GLib.MainContext.default().find_source_by_id(guard):
        GLib.source_remove(guard)
    cast.close()
    return res.get("path"), res.get("err"), (m.pw, m.ph)


# ---- decode helpers
def decode_audio(path):
    pipe = Gst.parse_launch(f'filesrc location="{path}" ! decodebin ! audioconvert ! audioresample ! '
                            'audio/x-raw,format=F32LE,channels=1,rate=48000 ! appsink name=s sync=false')
    sink_ = pipe.get_by_name("s")
    pipe.set_state(Gst.State.PLAYING)
    chunks = []
    while True:
        smp = sink_.emit("try-pull-sample", 2 * Gst.SECOND)
        if smp is None:
            break
        ok, info = smp.get_buffer().map(Gst.MapFlags.READ)
        chunks.append(np.frombuffer(info.data, dtype=np.float32).copy())
        smp.get_buffer().unmap(info)
    pipe.set_state(Gst.State.NULL)
    return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)


def tone_level(samples, freq, rate=48000):
    """Strength of one frequency relative to the whole signal (0..1), from the middle of the clip (skips start-up)."""
    n = len(samples)
    if n < rate:
        return 0.0
    seg = samples[rate // 2: n - rate // 4]
    seg = seg * np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg))
    bins = np.fft.rfftfreq(len(seg), 1 / rate)
    band = spec[(bins > freq - 6) & (bins < freq + 6)].max()
    return float(band / (spec.max() + 1e-9))


def decode_frames(path, count=6):
    pipe = Gst.parse_launch(f'filesrc location="{path}" ! decodebin ! videoconvert ! video/x-raw,format=RGB ! appsink name=s sync=false')
    sink_ = pipe.get_by_name("s")
    pipe.set_state(Gst.State.PLAYING)
    frames = []
    while len(frames) < 200:
        smp = sink_.emit("try-pull-sample", 2 * Gst.SECOND)
        if smp is None:
            break
        st = smp.get_caps().get_structure(0)
        w, h = st.get_value("width"), st.get_value("height")
        ok, info = smp.get_buffer().map(Gst.MapFlags.READ)
        stride = info.size // h
        frames.append(np.frombuffer(info.data, np.uint8).reshape(h, stride)[:, : w * 3].reshape(h, w, 3).copy())
        smp.get_buffer().unmap(info)
    pipe.set_state(Gst.State.NULL)
    return frames


def near(px, rgb, tol=60):
    return all(abs(int(a) - b) <= tol for a, b in zip(px, rgb))


try:
    # ---- the virtual desktop itself
    mons = screencast.list_monitors()
    check("headless session has one 1280x720 virtual monitor", len(mons) == 1 and (mons[0].pw, mons[0].ph) == (1280, 720),
          str([(m.connector, m.pw, m.ph) for m in mons]))
    devs = R.list_audio_devices()
    print("audio devices:", devs)
    names = [n for _l, n, _d in devs["inputs"] + devs["outputs"]]
    check("virtual speakers and microphones are listed", sink in names and mic_feed in names, str(names))
    check("a microphone is listed as an input, a speaker as an output",
          os.environ["VIRTUAL_DEFAULT_MIC"] in [n for _l, n, _d in devs["inputs"]] and sink in [n for _l, n, _d in devs["outputs"]], str(devs))

    pattern = start_pattern()
    t440 = tone(sink, 440)               # "system sound"
    t880 = tone(mic_feed, 880)           # "microphone"
    wait_loop(1500)

    mic_dev = f"{mic_feed}.monitor"
    SYS = {"kind": "pulse", "device": R.SYSTEM_AUDIO}
    MIC = {"kind": "pulse", "device": mic_dev}

    # A: whole screen, system sound only
    for fmt in ("mp4", "webm"):
        if not R.encoders_available()[fmt]:
            continue
        path, err, size = record(f"sys.{fmt}", fmt, [SYS])
        check(f"{fmt} system only: finished", path is not None, str(err))
        if not path:
            continue
        info = R.probe_file(path)
        check(f"{fmt} system only: size is the monitor's real pixels", info["video"] and info["video"][0][1:3] == (1280, 720), str(info["video"]))
        check(f"{fmt} system only: duration ~3 s", 2.3 <= info["duration"] <= 4.3, f"{info['duration']:.2f}")
        a = decode_audio(path)
        l440, l880 = tone_level(a, 440), tone_level(a, 880)
        check(f"{fmt} system only: 440 Hz speaker tone present, 880 Hz mic tone absent", l440 > 0.5 and l880 < 0.1, f"440={l440:.2f} 880={l880:.2f}")
        frames = decode_frames(path)
        check(f"{fmt} system only: frame count plausible", 60 <= len(frames) <= 110, str(len(frames)))
        f = frames[len(frames) // 2]
        h, w = f.shape[:2]
        check(f"{fmt} picture: red | green | blue bars where expected",
              near(f[h // 3, w // 6], (255, 0, 0)) and near(f[h // 3, w // 2], (0, 255, 0)) and near(f[h // 3, 5 * w // 6], (0, 0, 255)),
              str((f[h // 3, w // 6], f[h // 3, w // 2], f[h // 3, 5 * w // 6])))
        moved = sum(1 for i in range(1, len(frames)) if not np.array_equal(frames[i][-90:-10], frames[i - 1][-90:-10]))
        check(f"{fmt} the moving square moves (live frames, not one repeated image)", moved > len(frames) * 0.5, f"{moved}/{len(frames)}")

    # B: microphone only
    path, err, _ = record("mic.mp4", "mp4", [MIC])
    a = decode_audio(path) if path else np.zeros(0)
    l440, l880 = tone_level(a, 440), tone_level(a, 880)
    check("mic only: 880 Hz present, 440 Hz absent", path is not None and l880 > 0.5 and l440 < 0.1, f"440={l440:.2f} 880={l880:.2f} {err}")

    # C: both mixed
    path, err, _ = record("both.mp4", "mp4", [SYS, MIC])
    a = decode_audio(path) if path else np.zeros(0)
    l440, l880 = tone_level(a, 440), tone_level(a, 880)
    check("system + mic: both tones are in the mix", path is not None and l440 > 0.3 and l880 > 0.3, f"440={l440:.2f} 880={l880:.2f} {err}")
    check("system + mic: still one audio stream", path is not None and len(R.probe_file(path)["audio"]) == 1)

    # D: no audio
    path, err, _ = record("none.mp4", "mp4", [])
    info = R.probe_file(path) if path else {"audio": [1], "video": []}
    check("no audio requested: file has no audio stream", path is not None and info["audio"] == [] and len(info["video"]) == 1, str(err))

    # E: default microphone (silent here) records without error
    path, err, _ = record("defmic.mp4", "mp4", [{"kind": "pulse", "device": None}], seconds=2.0)
    check("default microphone: records and has an audio stream", path is not None and len(R.probe_file(path)["audio"]) == 1, str(err))

    # F: region crop at native pixels, bar boundary (x=427) inside the region
    path, err, _ = record("region.mp4", "mp4", [], crop=(200, 100, 401, 301), seconds=2.5)
    info = R.probe_file(path) if path else {"video": []}
    check("region: output is the even-sized region", info["video"] and info["video"][0][1:3] == (400, 300), str(info["video"]) + str(err))
    if path:
        f = decode_frames(path)[10]
        # source red/green boundary at x ~ 426.7 -> at ~ 226 in the crop
        check("region: red left of the boundary, green right of it", near(f[100, 150], (255, 0, 0)) and near(f[100, 300], (0, 255, 0)),
              str((f[100, 150], f[100, 300])))

    # G: cursor mode is accepted
    path, err, _ = record("cursor.mp4", "mp4", [], cursor=True, seconds=1.5)
    check("cursor embedded mode records", path is not None, str(err))

    # H: a still screen still gives a steady video (the stream only sends frames on change)
    pattern.terminate(); pattern.wait(); procs.remove(pattern)
    pattern = start_pattern(static=True)
    path, err, _ = record("still.mp4", "mp4", [], seconds=3.0)
    if path:
        n = R.count_video_frames(path)
        info = R.probe_file(path)
        check("still screen: ~30 fps video with no gaps", 70 <= n <= 110 and 2.5 <= info["duration"] <= 4.0, f"{n} frames, {info['duration']:.2f}s")
    else:
        check("still screen recorded", False, str(err))

    # I: stopping early then nothing left over
    check("no .part files left behind", not glob.glob(os.path.join(tmp, "*.part")))
finally:
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(3)
        except subprocess.TimeoutExpired:
            p.kill()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
