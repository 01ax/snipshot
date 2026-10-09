"""One screen recording from start to finish: picks the video source, resolves the audio devices, runs the recorder.

The GUI (app.py) only deals with this class: ``RecordingJob(...).start()`` and ``.stop()``, plus three callbacks.
"""
import os
import shutil

from gi.repository import GLib

import castsession
import config as CFG
import portal_cast
import recorder as R

LOW_DISK_BYTES = 100 * 1024 * 1024


def resolve_audio(cfg, system, mic, devices=None):
    """The audio sources to record, and notes about anything that had to be left out. Never raises: a missing
    microphone should not stop a screen recording, only be mentioned."""
    devs = devices if devices is not None else R.list_audio_devices()
    sources, notes = [], []
    if system:
        outs = [n for _l, n, _d in devs["outputs"]]
        node = cfg["record_system_device"]
        if node and node not in outs:
            notes.append("The chosen sound output is not connected, so the default output is used.")
            node = ""
        if outs:
            sources.append({"kind": "pulse", "device": f"{node}.monitor" if node else R.SYSTEM_AUDIO})
        else:
            notes.append("No sound output was found, so system sound is not recorded.")
    if mic:
        ins = [n for _l, n, _d in devs["inputs"]]
        node = cfg["record_mic_device"]
        if node and node not in ins:
            notes.append("The chosen microphone is not connected, so the default microphone is used.")
            node = ""
        if ins:
            sources.append({"kind": "pulse", "device": node or None})
        else:
            notes.append("No microphone was found, so the recording has no microphone sound.")
    return sources, notes


class RecordingJob:
    """target: {"kind": "monitor", "connector": "DP-2", "size": (w, h), "crop": (x, y, w, h) or None}
               {"kind": "window"}                        (the desktop asks which window)

    Callbacks (all on the GLib main loop):
      on_state(state)   "starting" -> ["ready" -> ] "recording" -> "stopping"
                        ("ready" only with auto_begin=False: the source is open and begin() starts the file, so the
                        caller can show a countdown in between)
      on_tick(seconds)  once a second while recording
      on_done(result)   once: {"path": str|None, "error": str|None, "warning": str|None, "notes": [str], "seconds": float,
                               "cancelled": bool}"""

    def __init__(self, cfg, target, system=None, mic=None, cursor=None, on_state=None, on_tick=None, on_done=None,
                 devices=None, auto_begin=True):
        self.cfg, self.target = cfg, target
        self.system = cfg["record_system_audio"] if system is None else system
        self.mic = cfg["record_mic"] if mic is None else mic
        self.cursor = cfg["record_cursor"] if cursor is None else cursor
        self.on_state = on_state or (lambda s: None)
        self.on_tick = on_tick or (lambda t: None)
        self.on_done = on_done or (lambda r: None)
        self.devices = devices
        self.auto_begin = auto_begin
        self._info = None
        self.state = "idle"
        self.rec = None
        self.cast = None
        self.notes = []
        self._tick_id = 0
        self._ticks = 0
        self._done = False

    # ------------------------------------------------------------------ start
    def start(self):
        if self.state != "idle":
            return
        self.state = "starting"
        self.on_state("starting")
        fmt = R.best_format(self.cfg["record_format"])
        if fmt is None:
            return self._finish(error="No video encoder is installed. Install the GStreamer plugins "
                                      "(gstreamer1.0-plugins-ugly and gstreamer1.0-libav, or gstreamer1.0-plugins-good).")
        self.fmt = fmt
        if fmt != self.cfg["record_format"]:
            self.notes.append(f"{self.cfg['record_format'].upper()} is not available here, so {fmt.upper()} is used.")
        try:
            self.audio, notes = resolve_audio(self.cfg, self.system, self.mic, self.devices)
        except GLib.Error:
            self.audio, notes = [], ["Sound devices could not be read, so the recording has no sound."]
        self.notes += notes
        if self.target["kind"] == "window":
            self.cast = portal_cast.WindowCast(cursor=self.cursor, on_closed=self._source_closed)
        else:
            self.cast = castsession.MonitorCast(self.target["connector"], cursor=self.cursor, size=self.target["size"],
                                                on_closed=self._source_closed)
        self.cast.open(self._opened)

    def _opened(self, info, err):
        if info is None:
            return self._finish(error=err, cancelled=err is None)
        if (info.get("size") or self.target.get("size")) is None:
            return self._finish(error="The screen capture did not report its size")
        self._info = info
        if self.auto_begin:
            self.begin()
        else:
            self.state = "ready"
            self.on_state("ready")

    def begin(self):
        """Start writing the file (the source is already open)."""
        if self._info is None or self.rec is not None or self._done:
            return
        info = self._info
        size = info.get("size") or self.target.get("size")
        video = {"kind": "pipewire", "node": info["node"], "fd": info.get("fd"), "size": tuple(size),
                 "crop": self.target.get("crop")}
        if self.target["kind"] == "window":
            video["fit"] = tuple(size)                    # windows can be resized mid-recording: keep one video size
        path = CFG.next_record_path(self.cfg, fmt=self.fmt)
        self.rec = R.Recorder(video, self.audio, path, self.fmt, int(self.cfg["record_fps"]), self.cfg["record_quality"],
                              on_done=self._recorder_done)
        self.rec.start()
        if self.rec.state != "recording":
            return                                        # start() already reported the failure through on_done
        self.state = "recording"
        self.on_state("recording")
        self._tick_id = GLib.timeout_add(1000, self._tick)

    # ------------------------------------------------------------------ while recording
    def _tick(self):
        self._ticks += 1
        self.on_tick(self.elapsed)
        if self._ticks % 5 == 0 and self.rec is not None:
            try:
                if shutil.disk_usage(os.path.dirname(self.rec.final_path)).free < LOW_DISK_BYTES:
                    self.rec.stop_early("The disk is nearly full, so the recording was stopped")
            except OSError:
                pass
        return self.state in ("recording", "stopping")

    @property
    def elapsed(self):
        return self.rec.elapsed if self.rec is not None else 0.0

    def stop(self):
        """Finish and save. Also cancels a recording that is still waiting for a window to be picked."""
        if self.state == "recording":
            self.state = "stopping"
            self.on_state("stopping")
            self.rec.stop()
        elif self.state in ("starting", "ready") and self.rec is None:
            self._finish(cancelled=True)

    def _source_closed(self):
        if self.rec is not None and self.state == "recording":
            self.rec.stop_early("The screen capture was ended by the system (was the screen locked, or the window closed?)")

    def _recorder_done(self, path, error):
        self._finish(path=path, error=error, warning=self.rec.warning if self.rec else None)

    def _finish(self, path=None, error=None, warning=None, cancelled=False):
        if self._done:
            return
        self._done = True
        seconds = self.elapsed
        self.state = "done"
        if self.cast is not None:
            self.cast.close()
        self.on_done({"path": path, "error": error, "warning": warning, "notes": list(self.notes), "seconds": seconds,
                      "cancelled": cancelled})


def fmt_time(seconds):
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"
