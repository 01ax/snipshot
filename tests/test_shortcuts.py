"""Shortcut helper against an IN-MEMORY settings backend: the real GNOME settings are never read or written."""
import os

os.environ["GSETTINGS_BACKEND"] = "memory"          # must be set before Gio is imported
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gi.repository import Gio
import config as CFG
import shortcuts as SH

fails = 0


def check(n, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), "-", n, extra, flush=True)


check("the in-memory backend is really in use", "Memory" in type(Gio.SettingsBackend.get_default()).__name__, type(Gio.SettingsBackend.get_default()).__name__)
EXE = "/home/test/.local/bin/snipshot"
st = SH.status(EXE)
check("fresh settings: both shortcuts missing", [s for _w, s, _e in st] == ["missing", "missing"], str(st))

res = SH.apply(EXE)
check("apply adds both", [r for _w, r in res] == ["added", "added"], str(res))
cur = SH.current()
check("entries have the right keys and commands", {(e["binding"], e["command"]) for e in cur} ==
      {("<Alt><Shift>g", EXE + " region"), ("<Alt><Shift>r", EXE + " record")}, str(cur))
check("apply twice changes nothing", [r for _w, r in SH.apply(EXE)] == ["ok", "ok"] and len(SH.current()) == 2)

# the person's own existing entry for the same command (different name, different keys) is updated in place, not duplicated
st_ = SH._settings()
st_.set_strv("custom-keybindings", [])
e = SH._entry(SH.BASE + "snip/")
e.set_string("name", "snip"); e.set_string("command", "/other/place/snipshot region"); e.set_string("binding", "<Super>p")
st_.set_strv("custom-keybindings", [SH.BASE + "snip/"])
res = SH.apply(EXE)
cur = {c["path"]: c for c in SH.current()}
check("an existing entry for the same command is reused and its keys corrected",
      res[0][1] == "updated" and len(cur) == 2 and cur[SH.BASE + "snip/"]["binding"] == "<Alt><Shift>g" and cur[SH.BASE + "snip/"]["name"] == "snip", str(res))

# another program holding Alt+Shift+R is never overwritten
st_.set_strv("custom-keybindings", [])
other = SH._entry(SH.BASE + "other/")
other.set_string("name", "Some recorder"); other.set_string("command", "somerec"); other.set_string("binding", "<Alt><Shift>r")
st_.set_strv("custom-keybindings", [SH.BASE + "other/"])
res = SH.apply(EXE)
check("a conflicting shortcut of another app is left alone and reported", res[1][1].startswith("conflict: Some recorder") and res[0][1] == "added", str(res))
check("the other app's shortcut is untouched", SH._entry(SH.BASE + "other/").get_string("command") == "somerec")
text = SH.describe(res)
check("the message is plain language", "Alt+Shift+R is already used by \"Some recorder\"" in text and "Alt+Shift+G now runs: region" in text, text)

# removing deletes only ours
removed = SH.remove(EXE)
check("remove deletes only Snipshot's entries", removed == ["Snipshot: capture"] and [c["name"] for c in SH.current()] == ["Some recorder"], str(removed))

# the dev copy manages only the recording shortcut, under its own names
CFG.CHANNEL = "dev"
w = SH.wanted("/home/test/.local/bin/snipshot-dev")
check("dev copy: only the record shortcut, with its own slug and command", len(w) == 1 and w[0]["slug"] == "snipshot-dev-record" and w[0]["command"].endswith("snipshot-dev record"), str(w))
CFG.CHANNEL = ""

print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
