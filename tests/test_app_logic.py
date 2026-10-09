"""Pure logic in app.py: command-line parsing and which screen `record screen` picks (no windows are opened)."""
import os
import sys
import tempfile

os.environ["SNIPSHOT_CONFIG_DIR"] = tempfile.mkdtemp(prefix="snipshot-logic-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A
import config as CFG
import recording as REC
import screencast as SCN

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


P = A.SnipshotApp.parse_opts
check("plain words pass through", P(["record", "screen", "DP-2"]) == (None, None, ["record", "screen", "DP-2"]))
check("--delay is read anywhere", P(["record", "--delay", "5"]) == (5.0, None, ["record"]) and P(["--delay=2", "region"]) == (2.0, None, ["region"]))
check("--audio none / system / mic / both", P(["--audio", "none"])[1] == set() and P(["--audio=system"])[1] == {"system"}
      and P(["--audio", "mic"])[1] == {"mic"} and P(["--audio=system,mic"])[1] == {"system", "mic"} and P(["--audio", "system+mic"])[1] == {"system", "mic"})
check("junk in --audio is ignored", P(["--audio", "banana,mic"])[1] == {"mic"})
check("old parse_args still returns (delay, rest)", A.SnipshotApp.parse_args(["--delay", "3", "region"]) == (3.0, ["region"]))
check("a bad --delay is ignored", P(["--delay", "soon", "region"])[0] is None)

M = lambda c, x, y, primary=False: SCN.MonitorInfo(c, x, y, 1920, 1080, 1.0, 1920, 1080, primary)       # noqa: E731
mons = [M("HDMI-1", 0, 0), M("DP-2", 1920, 0, True), M("DP-4", 3840, 0)]
pm = A.SnipshotApp.pick_monitor
check("default is the primary screen", pm(mons).connector == "DP-2")
check("left / right", pm(mons, "left").connector == "HDMI-1" and pm(mons, "right").connector == "DP-4")
check("by connector name, any case", pm(mons, "dp-4").connector == "DP-4")
check("by position number (1 = leftmost)", pm(mons, "1").connector == "HDMI-1" and pm(mons, "3").connector == "DP-4")
check("unknown name falls back to the primary", pm(mons, "nonsense").connector == "DP-2")
check("no monitors -> None", pm([]) is None)
check("no primary -> the first", pm([M("A", 0, 0), M("B", 10, 0)]).connector == "A")

check("timer text", REC.fmt_time(5) == "00:05" and REC.fmt_time(65) == "01:05" and REC.fmt_time(3725) == "1:02:05")

cfg = CFG.Config(os.path.join(os.environ["SNIPSHOT_CONFIG_DIR"], "c.json"))
cfg["record_dir"] = os.path.join(os.environ["SNIPSHOT_CONFIG_DIR"], "v")
a = CFG.next_record_path(cfg)
open(a, "w").close()
b = CFG.next_record_path(cfg)
check("recording names never overwrite", a != b and b.endswith("_2.mp4"), f"{os.path.basename(a)} {os.path.basename(b)}")
check("webm extension", CFG.next_record_path(cfg, fmt="webm").endswith(".webm"))
cfg["record_fps"], cfg["record_format"], cfg["record_quality"], cfg["record_countdown"] = 500, "avi", "ultra", 99
cfg.save()
c2 = CFG.Config(cfg.path)
check("bad recording settings are corrected on load", (c2["record_fps"], c2["record_format"], c2["record_quality"], c2["record_countdown"]) == (60, "mp4", "medium", 30),
      str((c2["record_fps"], c2["record_format"], c2["record_quality"], c2["record_countdown"])))
check("channel: the normal install shares nothing with a dev copy", CFG.APP_ID == "local.snipshot" and CFG.CHANNEL == "")

# resolve_audio: never raises, mentions what it left out
devs = {"inputs": [("Mic", "mic_a", True)], "outputs": [("Speakers", "sink_a", True)]}
c2["record_system_device"] = c2["record_mic_device"] = ""
src, notes = REC.resolve_audio(c2, True, True, devs)
check("both: default monitor + default mic", src == [{"kind": "pulse", "device": "@DEFAULT_MONITOR@"}, {"kind": "pulse", "device": None}] and not notes, str(src))
c2["record_system_device"], c2["record_mic_device"] = "sink_a", "mic_a"
src, notes = REC.resolve_audio(c2, True, True, devs)
check("chosen devices: sink monitor + mic by name", src == [{"kind": "pulse", "device": "sink_a.monitor"}, {"kind": "pulse", "device": "mic_a"}], str(src))
src, notes = REC.resolve_audio(c2, False, False, devs)
check("none requested: no sources", src == [] and notes == [])
src, notes = REC.resolve_audio(c2, True, True, {"inputs": [], "outputs": []})
check("no devices at all: no sources, two notes", src == [] and len(notes) == 2, str(notes))

print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
