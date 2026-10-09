"""GNOME keyboard shortcuts for Snipshot (Alt+Shift+G to capture, Alt+Shift+R to record), as custom keybindings.

GNOME has no API for apps to claim a global shortcut, so this writes the same "custom shortcut" entries the
Settings > Keyboard page does. Nothing here runs unless the person clicks the button in Preferences.
An existing entry that already launches our command is updated in place; an entry some OTHER program uses for the same
keys is never overwritten - it is reported as a conflict instead.
"""
import os

from gi.repository import Gio, GLib

import config as CFG

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = SCHEMA + ".custom-keybinding"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"

# (slug, label, keys, snipshot argument). The dev copy only manages the recording shortcut: the screenshot shortcut
# belongs to the normal install, and the two copies must not fight over it.
ALL = [("screenshot", "Snipshot: capture", "<Alt><Shift>g", "region"),
       ("record", "Snipshot: record", "<Alt><Shift>r", "record")]


def wanted(exe=None):
    exe = exe or os.path.expanduser(f"~/.local/bin/{CFG.APP_NAME}")
    suffix = f"-{CFG.CHANNEL}" if CFG.CHANNEL else ""
    rows = ALL if not CFG.CHANNEL else [r for r in ALL if r[3] == "record"]
    return [dict(slug=f"snipshot{suffix}-{slug}", name=label + (f" ({CFG.CHANNEL})" if CFG.CHANNEL else ""),
                 binding=keys, command=f"{exe} {arg}", arg=arg) for slug, label, keys, arg in rows]


def _settings():
    return Gio.Settings.new(SCHEMA)


def _entry(path):
    return Gio.Settings.new_with_path(CUSTOM_SCHEMA, path)


def current():
    """Every custom shortcut: [{path, name, binding, command}]."""
    out = []
    for path in _settings().get_strv("custom-keybindings"):
        e = _entry(path)
        out.append(dict(path=path, name=e.get_string("name"), binding=e.get_string("binding"), command=e.get_string("command")))
    return out


def _norm(binding):
    """'<Shift><Alt>g' and '<Alt><Shift>g' are the same keys: compare modifiers in a fixed order, case-insensitively."""
    mods, key = [], binding
    while key.startswith("<") and ">" in key:
        mods.append(key[1:key.index(">")].lower())
        key = key[key.index(">") + 1:]
    return "".join(f"<{m}>" for m in sorted(mods)) + key.lower()


def _same_launch(command, want):
    """True when ``command`` runs the same snipshot launcher with the same argument (paths compared by basename)."""
    a, b = command.split(), want.split()
    return len(a) >= 2 and len(b) >= 2 and os.path.basename(a[0]) == os.path.basename(b[0]) and a[1:] == b[1:]


def status(exe=None):
    """[(wanted entry, "ok" | "missing" | "different" | "conflict", the entry involved or None)]."""
    entries = current()
    out = []
    for w in wanted(exe):
        mine = next((e for e in entries if _same_launch(e["command"], w["command"])), None)
        if mine is not None:
            out.append((w, "ok" if _norm(mine["binding"]) == _norm(w["binding"]) else "different", mine))
            continue
        other = next((e for e in entries if _norm(e["binding"]) == _norm(w["binding"])), None)
        out.append((w, "conflict" if other else "missing", other))
    return out


def apply(exe=None):
    """Create or update the shortcuts. Returns [(wanted, what happened)] where what is "added", "updated", "ok" or
    "conflict: <name of the other shortcut>"."""
    results = []
    st = _settings()
    for w, state, entry in status(exe):
        if state == "conflict":
            results.append((w, f"conflict: {entry['name'] or entry['command']}"))
            continue
        if state == "ok":
            results.append((w, "ok"))
            continue
        paths = st.get_strv("custom-keybindings")
        path = entry["path"] if entry else BASE + w["slug"] + "/"
        e = _entry(path)
        e.set_string("name", w["name"] if not entry else entry["name"] or w["name"])
        e.set_string("command", w["command"] if not entry else entry["command"])
        e.set_string("binding", w["binding"])
        if path not in paths:
            st.set_strv("custom-keybindings", paths + [path])
        Gio.Settings.sync()
        results.append((w, "updated" if entry else "added"))
    return results


def remove(exe=None):
    """Delete only the entries this module would create (found by command)."""
    st = _settings()
    gone = []
    for w in wanted(exe):
        for e in current():
            if _same_launch(e["command"], w["command"]):
                paths = [p for p in st.get_strv("custom-keybindings") if p != e["path"]]
                st.set_strv("custom-keybindings", paths)
                ent = _entry(e["path"])
                for k in ("name", "command", "binding"):
                    ent.reset(k)
                gone.append(w["name"])
    Gio.Settings.sync()
    return gone


def describe(results):
    """One plain sentence per result, for a message box."""
    lines = []
    for w, what in results:
        keys = w["binding"].replace("<Alt>", "Alt+").replace("<Shift>", "Shift+").replace("<Super>", "Super+").replace("<Control>", "Ctrl+")
        keys = keys[:-1] + keys[-1].upper()
        if what.startswith("conflict"):
            lines.append(f"{keys} is already used by \"{what.split(': ', 1)[1]}\" - left alone.")
        elif what == "ok":
            lines.append(f"{keys} already runs: {w['arg']}")
        else:
            lines.append(f"{keys} now runs: {w['arg']} ({what})")
    return "\n".join(lines)
