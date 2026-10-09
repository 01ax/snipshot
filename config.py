"""Snipshot settings and file naming. No GUI imports.

Settings live in ~/.config/snipshot/config.json. The file-name pattern follows Greenshot's idea:
``${YYYY}-${MM}-${DD} ${hh}_${mm}_${ss}`` style variables inside a template.
"""
import json
import os
import re
import socket
import getpass
from datetime import datetime

# SNIPSHOT_CHANNEL=dev runs a side-by-side test copy that shares nothing with the normal install: its own application
# id (so both can run at once), settings folder, launcher name and icon name.
CHANNEL = os.environ.get("SNIPSHOT_CHANNEL", "").strip().lower()
APP_NAME = "snipshot" + (f"-{CHANNEL}" if CHANNEL else "")
APP_ID = "local.snipshot" + (f".{CHANNEL}" if CHANNEL else "")
DISPLAY_NAME = "Snipshot" + (f" ({CHANNEL})" if CHANNEL else "")
CONFIG_DIR = os.environ.get("SNIPSHOT_CONFIG_DIR") or os.path.expanduser(f"~/.config/{APP_NAME}")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    # output
    "output_dir": "~/Pictures/Screenshots",
    "filename_pattern": "Screenshot_${YYYY}-${MM}-${DD}_${hh}-${mm}-${ss}",
    "format": "png",                    # png | jpg | webp | bmp | tiff
    "jpg_quality": 90,
    # capture
    "after_capture": ["ask"],           # "ask" (destination menu, like Greenshot) or any of: editor, save, clipboard
    "capture_cursor": True,             # capture the mouse pointer as a movable object
    "show_notifications": True,
    "last_saved": "",
    "capture_delay_ms": 0,
    "last_region": None,                # {"monitor": "DP-2", "x": .., "y": .., "w": .., "h": ..} in that monitor's real pixels
    # screen recording
    "record_dir": "~/Videos/Screencasts",
    "record_name": "Recording_${YYYY}-${MM}-${DD}_${hh}-${mm}-${ss}",
    "record_format": "mp4",             # mp4 (H.264 + AAC) | webm (VP8 + Opus)
    "record_fps": 30,
    "record_quality": "medium",         # high | medium | low
    "record_countdown": 3,              # seconds between pressing Record and the first frame
    "record_system_audio": True,        # what you hear (the default output's monitor)
    "record_mic": False,
    "record_cursor": True,
    "record_system_device": "",         # "" = the default output; otherwise a sink's node name
    "record_mic_device": "",            # "" = the default microphone; otherwise a source's node name
    "last_recording": "",
    # editor
    "zoom_fit_on_open": True,
    "confirm_close_unsaved": True,
    "obfuscate_pixel_size": 10,
    "obfuscate_blur_radius": 10,
    "obfuscate_randomise": False,
    # general
    "autostart": False,
    "show_tray_icon": True,
    "recent_files": [],
}

FORMATS = ("png", "jpg", "webp", "bmp", "tiff")
RECORD_FORMATS = ("mp4", "webm")
EXT = {"png": "png", "jpg": "jpg", "webp": "webp", "bmp": "bmp", "tiff": "tiff"}


class Config(dict):
    """dict with defaults, loaded from and saved to JSON. Unknown keys are kept; bad values fall back."""

    def __init__(self, path=None):
        super().__init__(DEFAULTS)
        self.path = path or CONFIG_PATH
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for k, v in data.items():
                    if k in DEFAULTS and type(v) is not type(DEFAULTS[k]) and DEFAULTS[k] is not None:
                        continue                         # ignore wrongly-typed values
                    self[k] = v
        except (OSError, ValueError):
            pass
        if self["format"] not in FORMATS:
            self["format"] = "png"
        self["jpg_quality"] = min(100, max(1, int(self["jpg_quality"])))
        if self["record_format"] not in RECORD_FORMATS:
            self["record_format"] = "mp4"
        if self["record_quality"] not in ("high", "medium", "low"):
            self["record_quality"] = "medium"
        self["record_fps"] = min(60, max(5, int(self["record_fps"])))
        self["record_countdown"] = min(30, max(0, int(self["record_countdown"])))

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(dict(self), fh, indent=2)
        os.replace(tmp, self.path)

    @property
    def folder(self):
        return os.path.expanduser(self["output_dir"])

    @property
    def record_folder(self):
        return os.path.expanduser(self["record_dir"])

    def remember_file(self, path, limit=10):
        rec = [p for p in self["recent_files"] if p != path]
        self["recent_files"] = ([path] + rec)[:limit]


_VAR = re.compile(r"\$\{([A-Za-z]+)\}")
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize(name):
    name = _ILLEGAL.sub("_", name).strip().strip(".")
    return name[:150] or "Screenshot"


def expand_pattern(pattern, when=None, title="", number=0):
    """Fill in ${YYYY} ${MM} ${DD} ${hh} ${mm} ${ss} ${title} ${hostname} ${username} ${NUM}."""
    when = when or datetime.now()
    values = {
        "YYYY": f"{when.year:04d}", "MM": f"{when.month:02d}", "DD": f"{when.day:02d}",
        "hh": f"{when.hour:02d}", "mm": f"{when.minute:02d}", "ss": f"{when.second:02d}",
        "title": title or "", "hostname": socket.gethostname(), "username": getpass.getuser(),
        "NUM": f"{number:06d}",
    }
    return sanitize(_VAR.sub(lambda m: values.get(m.group(1), m.group(0)), pattern))


def unique_path(folder, base, ext):
    """folder/base.ext, or folder/base_2.ext, base_3.ext ... so nothing is ever overwritten silently."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{base}.{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base}_{n}.{ext}")
        n += 1
    return path


def next_save_path(cfg, when=None, title=""):
    base = expand_pattern(cfg["filename_pattern"], when, title)
    return unique_path(cfg.folder, base, EXT.get(cfg["format"], "png"))


def next_record_path(cfg, when=None, fmt=None):
    base = expand_pattern(cfg["record_name"], when, title="Recording")
    return unique_path(cfg.record_folder, base, fmt or cfg["record_format"])
