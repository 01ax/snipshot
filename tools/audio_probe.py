"""Measures how clean recorded system/microphone audio is, for a handful of audio settings, under CPU load.

    tools/headless_session.sh python3 -I tools/audio_probe.py

A pure tone is played into the private session's virtual speakers/microphone and recorded; any click, dropout or
timestamp jitter shows up as energy that is NOT the tone. Reported per setting: SNR of the tone in 100 ms windows
(worst and median, dB), and the number of windows below 25 dB or nearly silent."""
import itertools
import os
import subprocess
import sys
import tempfile
import time

if os.environ.get("SNIPSHOT_HEADLESS") != "1":
    sys.exit("Refusing to run outside tools/headless_session.sh")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import GLib, Gst  # noqa: E402
import recorder as R

R.ensure_gst()
sink, mic_feed = os.environ["VIRTUAL_SINK"], os.environ["VIRTUAL_MIC_FEED"]
loop = GLib.MainLoop()
tmp = tempfile.mkdtemp(prefix="snipshot-ap-")


def decode(path):
    pipe = Gst.parse_launch(f'filesrc location="{path}" ! decodebin ! audioconvert ! audioresample ! '
                            'audio/x-raw,format=F32LE,channels=1,rate=48000 ! appsink name=s sync=false')
    s = pipe.get_by_name("s")
    pipe.set_state(Gst.State.PLAYING)
    chunks = []
    while True:
        smp = s.emit("try-pull-sample", 2 * Gst.SECOND)
        if smp is None:
            break
        ok, info = smp.get_buffer().map(Gst.MapFlags.READ)
        chunks.append(np.frombuffer(info.data, np.float32).copy())
        smp.get_buffer().unmap(info)
    pipe.set_state(Gst.State.NULL)
    return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)


def metrics(x, freqs, rate=48000, win=4800):
    x = x[int(0.6 * rate): len(x) - int(0.3 * rate)]
    snrs, rms = [], []
    t = np.arange(win) / rate
    basis = np.stack([f(2 * np.pi * fr * t) for fr in freqs for f in (np.sin, np.cos)], axis=1)
    for i in range(0, len(x) - win, win):
        seg = x[i:i + win]
        coef, *_ = np.linalg.lstsq(basis, seg, rcond=None)
        fit = basis @ coef
        res = seg - fit
        snrs.append(10 * np.log10((fit ** 2).mean() / max((res ** 2).mean(), 1e-12)))
        rms.append(float(np.sqrt((seg ** 2).mean())))
    snrs, rms = np.array(snrs), np.array(rms)
    med = np.median(rms)
    return dict(windows=len(snrs), worst=float(snrs.min()), median=float(np.median(snrs)), bad=int((snrs < 25).sum()),
                gaps=int((rms < 0.3 * med).sum()))


def record(name, audio, seconds=8.0):
    out = os.path.join(tmp, name + ".mp4")
    res, timers = {}, []

    def done(p, e):
        res.update(p=p, e=e)
        for t in timers:
            if GLib.MainContext.default().find_source_by_id(t):
                GLib.source_remove(t)
        loop.quit()
    rec = R.Recorder({"kind": "test", "size": (1280, 720)}, audio, out, "mp4", 30, "medium", on_done=done)
    rec.start()
    timers.append(GLib.timeout_add(int(seconds * 1000), lambda: (rec.stop(), False)[1]))
    timers.append(GLib.timeout_add_seconds(int(seconds) + 15, loop.quit))
    loop.run()
    if not res.get("p"):
        print("   record failed:", res.get("e"), flush=True)
    return res.get("p")


def spawn(cmd):
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


tones = [spawn(["gst-launch-1.0", "-q", "audiotestsrc", "is-live=true", "freq=440", "volume=0.3", "!", "audioconvert", "!", "pulsesink", f"device={sink}"]),
         spawn(["gst-launch-1.0", "-q", "audiotestsrc", "is-live=true", "freq=880", "volume=0.3", "!", "audioconvert", "!", "pulsesink", f"device={mic_feed}"])]
time.sleep(1.5)
SYS = {"kind": "pulse", "device": R.SYSTEM_AUDIO}
MIC = {"kind": "pulse", "device": f"{mic_feed}.monitor"}
base = dict(R.AUDIO)                         # the shipped defaults; each variant overrides some of them
variants = {
    "A as it was (do-timestamp)": dict(do_timestamp=True, bypass_single=False, mixer_latency_ms=0),
    "H shipped defaults": {},
    "B no do-timestamp": dict(do_timestamp=False, bypass_single=False, mixer_latency_ms=0),
    "C no do-timestamp + provide-clock": dict(do_timestamp=False, provide_clock=True, bypass_single=False, mixer_latency_ms=0),
}
only = sys.argv[1:] or None
load = [subprocess.Popen(["nice", "-n", "19", sys.executable, "-c", "while True: pass"]) for _ in range(int(os.environ.get("PROBE_LOAD", "6")))]
try:
    for label, tune in variants.items():
        if only and not any(o in label for o in only):
            continue
        R.AUDIO.clear(); R.AUDIO.update(base); R.AUDIO.update(tune)
        line = f"{label:44s}"
        for name, audio, freqs in (("sys", [SYS], [440]), ("sys+mic", [SYS, MIC], [440, 880])):
            p = record(label[:1] + name.replace("+", ""), audio)
            m = metrics(decode(p), freqs) if p else None
            line += f" | {name}: " + (f"worst {m['worst']:5.1f} dB  median {m['median']:5.1f}  bad {m['bad']:2d}/{m['windows']}  gaps {m['gaps']}" if m else "FAILED")
        print(line, flush=True)
finally:
    for p in tones + load:
        p.terminate()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
