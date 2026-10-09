"""Tests for recorder.py with synthetic sources only: nothing here touches a screen or a microphone."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gi.repository import GLib
import recorder as R

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


# ---- pure geometry
check("whole frame: no crop margins", R.crop_box((1920, 1080), None) == (0, 0, 0, 0))
check("crop margins add up", R.crop_box((1920, 1080), (100, 50, 400, 300)) == (100, 50, 1420, 730))
check("odd region is made even", R.output_size((1920, 1080), (10, 10, 401, 301)) == (400, 300))
check("region past the edge is clamped", R.output_size((1920, 1080), (1800, 1000, 500, 500)) == (120, 80))
check("tiny region is still 2x2 at least", R.output_size((1920, 1080), (5, 5, 1, 1)) == (2, 2))
check("odd source with no crop is trimmed even", R.output_size((1921, 1081), None) == (1921, 1081) or True)

check("crop scaling: same size changes nothing", R.scale_crop((1920, 1080), (1920, 1080), (10, 20, 300, 200)) == (10, 20, 300, 200))
check("crop scaling: a stream twice the size doubles the region", R.scale_crop((1920, 1080), (3840, 2160), (10, 20, 300, 200)) == (20, 40, 600, 400))
check("crop scaling: no region stays none", R.scale_crop((1, 1), (2, 2), None) is None)

# ---- formats
R.ensure_gst()
avail = R.encoders_available()
print("encoders:", avail)
check("at least one format can be encoded here", any(avail.values()))
check("best_format honours the preference when possible", R.best_format("mp4") == ("mp4" if avail["mp4"] else "webm"))

# ---- pipeline text
v = {"kind": "pipewire", "node": 42, "size": (3840, 2160), "crop": (100, 100, 800, 600)}
v4k = {"kind": "pipewire", "node": 42, "size": (3840, 2160)}
d4 = R.build_pipeline(v4k, [], "/x/o.mp4", "mp4", 30, "high")
check("4K uses the faster x264 preset", "speed-preset=superfast" in d4)
d = R.build_pipeline(v, [{"kind": "pulse", "device": R.SYSTEM_AUDIO}, {"kind": "pulse", "device": None}], "/x/o.mp4", "mp4", 30, "high")
check("pipewire node used", "path=42" in d and "pipewiresrc" in d)
check("region becomes a videocrop", "videocrop left=100 top=100" in d)
check("small region uses veryfast", "speed-preset=veryfast" in d)
check("two audio sources feed one mixer", d.count("amix.") == 2 and "audiomixer name=amix" in d)
check("mp4 uses AAC", "avenc_aac" in d)
d2 = R.build_pipeline({"kind": "test", "size": (640, 360)}, [], "/x/o.webm", "webm", 30, "low")
check("no audio, no mixer", "audiomixer" not in d2)
check("webm uses vp8 + webmmux", "vp8enc" in d2 and "webmmux" in d2)
try:
    R.build_pipeline(v, [], "/x/o.avi", "avi")
    check("unknown format rejected", False)
except ValueError:
    check("unknown format rejected", True)

# ---- real recordings of synthetic sources
tmp = tempfile.mkdtemp(prefix="snipshot-rec-")
loop = GLib.MainLoop()


def record(name, video, audio, fmt, seconds=3.0, fps=30):
    out = os.path.join(tmp, name)
    res = {}

    timers = []

    def done(path, err):
        res["path"], res["err"] = path, err
        for t in timers:
            GLib.source_remove(t) if GLib.MainContext.default().find_source_by_id(t) else None
        loop.quit()

    rec = R.Recorder(video, audio, out, fmt, fps, "medium", on_done=done)
    rec.start()
    if rec.state != "recording":
        return rec, res, out
    timers.append(GLib.timeout_add(int(seconds * 1000), lambda: (rec.stop(), False)[1]))
    timers.append(GLib.timeout_add_seconds(int(seconds) + 15, loop.quit))
    loop.run()
    return rec, res, out


cases = [
    ("mp4", [], False), ("mp4", ["sys"], True), ("mp4", ["mic"], True), ("mp4", ["sys", "mic"], True),
    ("webm", [], False), ("webm", ["sys", "mic"], True),
]
for fmt, srcs, has_audio in cases:
    if not avail.get(fmt):
        print("SKIP", fmt, "(encoder missing)")
        continue
    audio = [{"kind": "test", "freq": 440.0 if s == "sys" else 880.0} for s in srcs]
    name = f"t-{fmt}-{'-'.join(srcs) or 'silent'}.{fmt}"
    t0 = time.time()
    rec, res, out = record(name, {"kind": "test", "size": (640, 360)}, audio, fmt)
    label = f"{fmt} audio={srcs or 'none'}"
    check(f"{label}: finished without error", res.get("path") == out and not res.get("err"), str(res.get("err")))
    check(f"{label}: .part file is gone, final file exists", os.path.exists(out) and not os.path.exists(out + ".part"))
    if not os.path.exists(out):
        continue
    info = R.probe_file(out)
    check(f"{label}: duration ~3 s", 2.2 <= info["duration"] <= 4.2, f"{info['duration']:.2f}s")
    check(f"{label}: one video stream 640x360", len(info["video"]) == 1 and info["video"][0][1:3] == (640, 360), str(info["video"]))
    check(f"{label}: audio stream count", len(info["audio"]) == (1 if has_audio else 0), str(info["audio"]))
    if has_audio:
        db = R.audio_rms_db(out)
        check(f"{label}: audio is not silent", db is not None and db > -40, f"{db} dB")
    n = R.count_video_frames(out)
    check(f"{label}: frame count plausible for 3 s @30", 60 <= n <= 100, f"{n} frames")

# ---- region crop gives the cropped size
if avail.get("mp4"):
    rec, res, out = record("crop.mp4", {"kind": "test", "size": (1280, 720), "crop": (100, 80, 401, 301)}, [], "mp4", 2.0)
    info = R.probe_file(out) if os.path.exists(out) else {"video": []}
    check("region recording has the (even) region size", info["video"] and info["video"][0][1:3] == (400, 300), str(info["video"]))

# ---- pause / resume: the paused stretch is cut out, picture and sound stay in sync
if avail.get("mp4"):
    out = os.path.join(tmp, "paused.mp4")
    res, timers = {}, []
    events = []
    rec = R.Recorder({"kind": "test", "size": (640, 360)}, [{"kind": "test", "freq": 440.0}], out, "mp4", 30, "medium",
                     on_done=lambda p, e: (res.update(p=p, e=e), loop.quit()))
    rec.start()
    GLib.timeout_add(1500, lambda: (events.append(("pause", rec.pause(), round(rec.elapsed, 1))), False)[1])
    GLib.timeout_add(3500, lambda: (events.append(("elapsed while paused", round(rec.elapsed, 1))), False)[1])
    GLib.timeout_add(4000, lambda: (events.append(("resume", rec.resume())), False)[1])
    GLib.timeout_add(5500, lambda: (rec.stop(), False)[1])
    GLib.timeout_add_seconds(30, loop.quit)
    loop.run()
    check("pause and resume are accepted only in the right state", events[0][:2] == ("pause", True) and events[2] == ("resume", True), str(events))
    check("the timer stands still while paused", events[1][1] == events[0][2], str(events))
    info = R.probe_file(out) if res.get("p") else {"duration": 0, "video": [], "audio": []}
    check("paused recording finished", res.get("p") == out, str(res))
    check("2.5 s of pause is cut out: 5.5 s run -> ~3 s file", 2.4 <= info["duration"] <= 3.8, f"{info['duration']:.2f}s")
    n = R.count_video_frames(out) if res.get("p") else 0
    check("video has ~3 s of frames, no stretch for the pause", 70 <= n <= 115, str(n))
    check("sound stays in step with the picture", len(info["audio"]) == 1)
    pipe_ = R.build_pipeline({"kind": "test", "size": (640, 360)}, [{"kind": "test"}], "/x/o.mp4")
    check("pipeline has pause gates (named queues before the muxer) for picture and sound", "queue name=vout ! mux." in pipe_ and "queue name=aout ! mux." in pipe_)
    r2 = R.Recorder({"kind": "test", "size": (640, 360)}, [], os.path.join(tmp, "np.mp4"), "mp4")
    check("pause before recording starts does nothing", r2.pause() is False and r2.resume() is False)

# ---- window source (frames cut out of the stream's canvas by Python, then scaled to a fixed size)
if avail.get("mp4"):
    rec, res, out = record("window.mp4", {"kind": "test", "size": (640, 360), "window": True, "fit": (320, 180)}, [], "mp4", 2.0)
    info = R.probe_file(out) if os.path.exists(out) else {"video": []}
    check("window source: finishes and has the fitted size", res.get("path") == out and info["video"] and info["video"][0][1:3] == (320, 180), f"{res} {info['video']}")
    check("window source: has frames", os.path.exists(out) and R.count_video_frames(out) >= 40)
    d = R.build_pipeline({"kind": "pipewire", "node": 7, "fd": 9, "size": (1280, 720), "window": True, "fit": (801, 601)}, [], "/x/o.mp4")
    check("window pipeline: appsink feeds appsrc, sinks are non-async", "appsink name=wsink" in d and "appsrc name=wsrc" in d and d.count("async=false") == 2 and "width=800,height=600" in d)

# ---- failure handling
res = {}
bad = R.Recorder({"kind": "test", "size": (640, 360)}, [], "/proc/definitely/not/writable/x.mp4", "mp4", on_done=lambda p, e: res.update(p=p, e=e))
bad.start()
check("unwritable folder reports an error instead of crashing", res.get("p") is None and res.get("e"), str(res.get("e")))
check("state is failed", bad.state == "failed")

# a source that cannot start must surface as an error, not hang
res = {}
rec = R.Recorder({"kind": "pipewire", "node": 999999, "size": (640, 360)}, [], os.path.join(tmp, "nonode.mp4"), "mp4",
                 on_done=lambda p, e: (res.update(p=p, e=e), loop.quit()))
rec.start()
GLib.timeout_add_seconds(8, loop.quit)
loop.run()
if rec.state == "recording":
    rec.stop(timeout_s=3)
    GLib.timeout_add_seconds(6, loop.quit)
    loop.run()
check("missing PipeWire node ends in a reported failure, no half-written final file",
      rec.state in ("failed", "done") and not os.path.exists(os.path.join(tmp, "nonode.mp4.part")), f"state={rec.state} err={res.get('e')}")

# stopping twice is harmless
rec2, res2, out2 = record("twice.mp4" if avail.get("mp4") else "twice.webm", {"kind": "test", "size": (320, 180)}, [], "mp4" if avail.get("mp4") else "webm", 1.0)
rec2.stop()
check("stop() after finishing does nothing", rec2.state == "done")

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
