"""The commands run before a recording starts and after it ends (record_start_command / record_stop_command).
Plain test: the screen capture is replaced by a stand-in, so nothing is recorded and no display is needed."""
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gi.repository import GLib
import config as CFG
import recording

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


tmp = tempfile.mkdtemp(prefix="snipshot-hooks-")
trace = os.path.join(tmp, "trace")


def script(name, body):
    path = os.path.join(tmp, name)
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class FakeCast:
    """Stands in for the Mutter ScreenCast session; notes when it is opened and closed."""
    def __init__(self, *a, **k):
        pass

    def open(self, cb):
        open(trace, "a").write("cast-open\n")
        GLib.idle_add(lambda: (cb(None, "no capture in this test"), False)[1])

    def close(self):
        open(trace, "a").write("cast-close\n")


recording.castsession.MonitorCast = FakeCast


def run(start_cmd, stop_cmd):
    open(trace, "w").close()
    cfg = CFG.Config(path=os.path.join(tmp, "config.json"))
    cfg["record_start_command"], cfg["record_stop_command"] = start_cmd, stop_cmd
    cfg["record_dir"] = tmp
    loop = GLib.MainLoop()
    out = {}
    job = recording.RecordingJob(cfg, {"kind": "monitor", "connector": "DP-9", "size": (640, 360), "crop": None},
                                 system=False, mic=False, devices={"outputs": [], "inputs": []},
                                 on_done=lambda r: (out.update(r), GLib.timeout_add(400, loop.quit)))
    GLib.timeout_add(100, lambda: (job.start(), False)[1])
    GLib.timeout_add(8000, loop.quit)
    loop.run()
    return out, [l for l in open(trace).read().splitlines() if l]


# the start command runs first, the capture opens only afterwards, and the stop command runs once it is over
start = script("start.sh", f"echo start >> {trace}")
stop = script("stop.sh", f"echo stop >> {trace}")
out, events = run(start, stop)
check("start command, then the capture, then the stop command", events == ["start", "cast-open", "cast-close", "stop"], events)

# nothing configured: nothing runs, nothing is mentioned
out, events = run("", "")
check("no commands set: just the capture", events == ["cast-open", "cast-close"], events)
check("no commands set: no note", not out.get("notes"), out.get("notes"))

# a command with arguments (the shell's quoting is honoured)
arg = script("arg.sh", f'echo "$1-$2" >> {trace}')
out, events = run(f'{arg} "two words" x', "")
check("arguments and quoting are passed on", events[:1] == ["two words-x"], events)

# a failing start command does not stop the recording from being attempted, and is reported; no stop command then
broken = script("broken.sh", "exit 3")
out, events = run(broken, stop)
check("a failing start command is reported", any("record_start_command" in n for n in out.get("notes", [])), out.get("notes"))
check("a failing start command: capture still tried, stop command not run", events == ["cast-open", "cast-close"], events)

# a command that is not there at all
out, events = run("/nonexistent/command", stop)
check("a missing command is reported, not raised", any("record_start_command" in n for n in out.get("notes", [])), out.get("notes"))

# stopped while the start command is still settling: the capture never opens, the stop command still runs
open(trace, "w").close()
cfg = CFG.Config(path=os.path.join(tmp, "config2.json"))
cfg["record_start_command"], cfg["record_stop_command"], cfg["record_dir"] = start, stop, tmp
loop = GLib.MainLoop()
res = {}
job = recording.RecordingJob(cfg, {"kind": "monitor", "connector": "DP-9", "size": (640, 360), "crop": None}, system=False, mic=False,
                             devices={"outputs": [], "inputs": []}, on_done=lambda r: (res.update(r), GLib.timeout_add(1500, loop.quit)))
GLib.timeout_add(100, lambda: (job.start(), job.stop(), False)[2])
GLib.timeout_add(8000, loop.quit)
loop.run()
events = [l for l in open(trace).read().splitlines() if l]
check("cancelled during the settle delay: no capture, stop command runs", events == ["start", "stop"] and res.get("cancelled"), (events, res))

print("FAILED" if fails else "ALL PASSED")
sys.exit(1 if fails else 0)
