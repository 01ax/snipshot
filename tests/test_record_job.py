"""RecordingJob against the PRIVATE headless GNOME session (start it with tools/headless_session.sh):
file naming, audio resolution, early end when the compositor closes the session, low-disk stop, cancel."""
import glob
import os
import subprocess
import sys
import tempfile

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("Refusing to run: start this with tools/headless_session.sh so it never records a real screen.")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gi.repository import GLib
import config as CFG
import recording as REC
import recorder as R
import screencast

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


tmp = tempfile.mkdtemp(prefix="snipshot-job-")
cfg = CFG.Config(os.path.join(tmp, "config.json"))
cfg["record_dir"] = os.path.join(tmp, "videos")
cfg["record_countdown"] = 0
loop = GLib.MainLoop()
m = screencast.list_monitors()[0]
TARGET = {"kind": "monitor", "connector": m.connector, "size": (m.pw, m.ph), "crop": None}
procs = [subprocess.Popen([sys.executable, "-I", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "test_pattern.py")],
                          env=dict(os.environ, WAYLAND_DISPLAY=sorted(os.path.basename(p) for p in glob.glob(os.environ["XDG_RUNTIME_DIR"] + "/wayland-*") if not p.endswith(".lock"))[0], GDK_BACKEND="wayland"),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]


def decode_audio_levels(path):
    return R.audio_rms_db(path)


def run_job(target=TARGET, seconds=2.5, before_stop=None, **kw):
    res, states = {}, []
    job = REC.RecordingJob(cfg, target, on_state=states.append, on_done=lambda r: (res.update(r), loop.quit()), **kw)
    job.start()
    if before_stop:
        GLib.timeout_add(int(seconds * 700), lambda: (before_stop(job), False)[1])
    GLib.timeout_add(int(seconds * 1000), lambda: (job.stop(), False)[1])
    guard = GLib.timeout_add_seconds(int(seconds) + 25, loop.quit)
    loop.run()
    GLib.source_remove(guard) if GLib.MainContext.default().find_source_by_id(guard) else None
    return job, res, states


try:
    GLib.timeout_add(2500, loop.quit); loop.run()                     # let the test window appear

    job, res, states = run_job(system=True, mic=True, cursor=True)
    check("job ends with a saved file in the recordings folder", res.get("path") and os.path.dirname(res["path"]) == cfg.record_folder, str(res))
    check("file name follows the pattern", res.get("path") and os.path.basename(res["path"]).startswith("Recording_") and res["path"].endswith(".mp4"))
    check("states went starting -> recording -> stopping", states == ["starting", "recording", "stopping"], str(states))
    check("no error, no warning, no notes", not res.get("error") and not res.get("warning") and not res.get("notes"), str(res))
    info = R.probe_file(res["path"])
    check("system + mic gives one audio stream", len(info["audio"]) == 1, str(info))
    check("duration reported close to the real one", abs(res["seconds"] - info["duration"]) < 1.5, f"{res['seconds']:.2f} vs {info['duration']:.2f}")

    job, res, states = run_job(system=False, mic=False)
    check("no audio requested: none recorded", res.get("path") and R.probe_file(res["path"])["audio"] == [])

    nomic = {"inputs": [], "outputs": [("Speakers", "x", True)]}
    job, res, states = run_job(system=False, mic=True, devices=nomic)
    check("missing microphone: recording still works, with a note",
          res.get("path") and R.probe_file(res["path"])["audio"] == [] and any("No microphone" in n for n in res["notes"]), str(res.get("notes")))

    cfg["record_mic_device"] = "does_not_exist"
    job, res, states = run_job(system=False, mic=True)
    check("unknown chosen microphone falls back to the default, with a note",
          res.get("path") and len(R.probe_file(res["path"])["audio"]) == 1 and any("not connected" in n for n in res["notes"]), str(res.get("notes")))
    cfg["record_mic_device"] = ""

    cfg["record_format"] = "webm"
    job, res, states = run_job(system=False, mic=False)
    check("webm setting gives a .webm file", res.get("path", "").endswith(".webm"), str(res))
    cfg["record_format"] = "mp4"

    # the compositor ends the session by itself (screen lock, session stop): keep what was recorded
    def kill_session(job):
        job.cast._call(job.cast.session, castsession_SC + ".Session", "Stop", None, None)
    import castsession
    castsession_SC = castsession.SC
    job, res, states = run_job(seconds=5.0, before_stop=kill_session, system=False, mic=False)
    check("session closed by the system: a playable file is kept, with a warning",
          res.get("path") and os.path.getsize(res["path"]) > 0 and res.get("warning"), str({k: v for k, v in res.items() if k != "notes"}))
    if res.get("path"):
        d = R.probe_file(res["path"])
        check("  ... and it has the part that was recorded", d["video"] and 1.0 <= d["duration"] <= 5.0, f"{d['duration']:.2f}s")

    # pause / resume through the real ScreenCast stream: the paused stretch is cut out, sound and picture stay in step
    ptimes = {}

    def do_pause(job):
        ptimes["elapsed_at_pause"] = round(job.elapsed, 2)
        job.pause()
        ptimes["after pause"] = (job.state, job.rec.state)

        def later():
            ptimes["elapsed_paused"] = round(job.elapsed, 2)
            job.toggle_pause()
            ptimes["after_resume"] = job.state
            return False
        GLib.timeout_add(2000, later)
    job, res, states = run_job(seconds=8.0, before_stop=lambda j: GLib.timeout_add(0, lambda: (do_pause(j), False)[1]), system=True, mic=False)
    check("pause: states go recording -> paused -> recording -> stopping", states == ["starting", "recording", "paused", "recording", "stopping"], str(states))
    check("pause: pause()/toggle_pause() change the job and recorder state", ptimes.get("after pause") == ("paused", "paused") and ptimes.get("after_resume") == "recording", str(ptimes))
    check("pause: the timer stood still for the 2 s pause", abs(ptimes.get("elapsed_paused", 99) - ptimes.get("elapsed_at_pause", -99)) < 0.3, str(ptimes))
    if res.get("path"):
        info = R.probe_file(res["path"])
        check("pause: 2 s of pause is cut out of an ~8 s run (~6 s file)", 5.0 <= info["duration"] <= 7.0, f"{info['duration']:.2f}s")
        check("pause: still one video and one audio stream", len(info["video"]) == 1 and len(info["audio"]) == 1, str(info))
        n = R.count_video_frames(res["path"])
        check("pause: ~6 s of frames (not stretched, not 8 s)", 150 <= n <= 215, str(n))
        a = decode_audio_levels(res["path"])
        check("pause: sound runs the whole file (no silent hole where the pause was)", a is not None, "")
    else:
        check("pause: recording saved", False, str(res))

    # low disk space stops the recording instead of filling the disk
    REC.LOW_DISK_BYTES = 10 ** 18
    job, res, states = run_job(seconds=9.0, system=False, mic=False)
    check("low disk space ends the recording early, keeping the file", res.get("path") and res.get("warning") and "disk" in res["warning"], str(res.get("warning")))
    REC.LOW_DISK_BYTES = 100 * 1024 * 1024

    # cancel while starting never leaves files behind
    left = glob.glob(os.path.join(cfg.record_folder, "*.part"))
    check("no .part files left in the recordings folder", not left, str(left))

    # unavailable format falls back
    cfg["record_format"] = "mp4"
    orig = R.encoders_available
    R.encoders_available = lambda: {"mp4": False, "webm": True}
    job, res, states = run_job(system=False, mic=False)
    check("missing H.264 encoder: falls back to WebM with a note", res.get("path", "").endswith(".webm") and any("MP4" in n for n in res["notes"]), str(res))
    R.encoders_available = lambda: {"mp4": False, "webm": False}
    job, res, states = run_job(system=False, mic=False, seconds=0.5)
    check("no encoder at all: clear error", not res.get("path") and res.get("error") and "encoder" in res["error"], str(res.get("error")))
    R.encoders_available = orig
finally:
    for p in procs:
        p.terminate()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
