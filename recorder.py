"""Screen recording for Snipshot: a GStreamer pipeline builder and a small controller.

Video comes from a PipeWire stream (Mutter's ScreenCast for a monitor or region, or the desktop portal for a
window) and is encoded to H.264 in MP4 or VP8 in WebM. Audio is optional and mixed from up to two sources:
the system sound (the "monitor" of the default output) and the microphone, so you can record either, both or
neither. The builders take plain dictionaries, so tests can swap in synthetic video and tone sources and run
without touching a screen or a microphone.

Video source dict:  {"kind": "pipewire", "node": int, "fd": int|None, "size": (w, h), "crop": (x, y, w, h)|None}
                    {"kind": "test", "size": (w, h), "crop": (x, y, w, h)|None}
                    optional "fit": (w, h): scale whatever arrives to this size (black borders keep the aspect ratio).
                    optional "window": True: a window stream. Mutter sends a fixed-size canvas with the window drawn in
                    one corner and says where it is in each frame's crop metadata; the recorder cuts that rectangle out
                    of every frame (it follows the window when it is resized) and scales it to "fit", because a video
                    file cannot change size part-way.
Audio source dict:  {"kind": "pulse", "device": "@DEFAULT_MONITOR@" | node name | None}   None = default input
                    {"kind": "test", "freq": 440.0}
"""
import ctypes
import os
import re
import shutil
import time

import gi
import numpy as np

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
gi.require_version("GstPbutils", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import GLib, Gst, GstApp, GstPbutils, GstVideo  # noqa: E402,F401

FORMATS = {
    "mp4": dict(ext="mp4", label="MP4 (H.264 + AAC)", needs=("x264enc", "avenc_aac", "mp4mux")),
    "webm": dict(ext="webm", label="WebM (VP8 + Opus)", needs=("vp8enc", "opusenc", "webmmux")),
}
# constant-quality settings: lower number = better picture, bigger file
QUALITY = {"high": dict(x264=20, vp8=8), "medium": dict(x264=25, vp8=18), "low": dict(x264=30, vp8=32)}
SYSTEM_AUDIO = "@DEFAULT_MONITOR@"       # what you hear: the monitor of the default output
MIN_FREE_BYTES = 300 * 1024 * 1024


def ensure_gst():
    if not Gst.is_initialized():
        Gst.init(None)


def encoders_available():
    """{format: True/False}: which containers this machine can encode."""
    ensure_gst()
    return {k: all(Gst.ElementFactory.find(e) is not None for e in v["needs"]) for k, v in FORMATS.items()}


def best_format(preferred="mp4"):
    """The preferred format if it can be encoded here, else any format that can, else None."""
    avail = encoders_available()
    if avail.get(preferred):
        return preferred
    return next((k for k, ok in avail.items() if ok), None)


# --------------------------------------------------------------------------- audio devices

def list_audio_devices():
    """{"inputs": [(label, node_name, is_default)], "outputs": [(label, node_name, is_default)]}.

    Names only, nothing is captured. Inputs are microphones; outputs are listed so their 'monitor' (what you hear)
    can be recorded as "system sound". Node names are what PulseAudio-compatible sources are addressed by."""
    ensure_gst()
    mon = Gst.DeviceMonitor.new()
    mon.add_filter("Audio/Source", None)
    mon.add_filter("Audio/Sink", None)
    mon.start()
    inputs, outputs, seen = [], [], set()
    try:
        for d in mon.get_devices():
            p = d.get_properties()
            if p is None or not p.has_field("node.name"):
                continue
            node = p.get_string("node.name")
            klass = p.get_string("media.class") or ""
            is_source = d.has_classes("Audio/Source")
            is_monitor = (p.get_string("device.class") == "monitor")
            default = bool(p.get_value("is-default")) if p.has_field("is-default") else False
            label = d.get_display_name()
            key = (is_source, node)
            if key in seen or is_monitor:
                continue
            seen.add(key)
            (inputs if is_source else outputs).append((label, node, default))
    finally:
        mon.stop()
    return {"inputs": inputs, "outputs": outputs}


def monitor_of(sink_node):
    return f"{sink_node}.monitor"


# --------------------------------------------------------------------------- window streams

def read_crop_meta(buf):
    """(x, y, w, h) from a buffer's GstVideoCropMeta, or None. PyGObject cannot cast a generic GstMeta, so the four
    guints that follow the GstMeta header (flags + info pointer) are read directly."""
    try:
        meta = buf.get_meta(GstVideo.video_crop_meta_api_get_type())
        if not meta:
            return None
        base = hash(meta) & 0xFFFFFFFFFFFFFFFF
        x, y, w, h = (ctypes.c_uint * 4).from_address(base + 2 * ctypes.sizeof(ctypes.c_void_p))
        return (int(x), int(y), int(w), int(h)) if w and h else None
    except Exception:                                        # noqa: BLE001 - an unreadable hint just means "no crop"
        return None


def window_geometry(video, timeout_s=3.0):
    """Look at the first frame of a window stream: ((canvas_w, canvas_h), (x, y, w, h) of the window or None).
    Returns None if no frame arrived in time."""
    ensure_gst()
    opts = f"fd={video['fd']} " if video.get("fd") is not None else ""
    pipe = Gst.parse_launch(f"pipewiresrc {opts}path={video['node']} always-copy=true ! video/x-raw ! "
                            "appsink name=s sync=false max-buffers=1 drop=true")
    sink = pipe.get_by_name("s")
    pipe.set_state(Gst.State.PLAYING)
    try:
        sample = sink.emit("try-pull-sample", int(timeout_s * Gst.SECOND))
        if sample is None:
            return None
        st = sample.get_caps().get_structure(0)
        return (st.get_value("width"), st.get_value("height")), read_crop_meta(sample.get_buffer())
    finally:
        pipe.set_state(Gst.State.NULL)


def scale_crop(expected, actual, crop):
    """A region chosen in ``expected``-sized pixels, expressed in ``actual``-sized pixels (the stream is not always the
    size the display configuration suggests, e.g. on fractionally scaled monitors)."""
    if crop is None or tuple(expected) == tuple(actual):
        return crop
    fx, fy = actual[0] / expected[0], actual[1] / expected[1]
    x, y, w, h = crop
    return (round(x * fx), round(y * fy), round(w * fx), round(h * fy))


# --------------------------------------------------------------------------- pipeline description

def _even(n):
    return int(n) - (int(n) % 2)


def crop_box(size, crop):
    """(left, top, right, bottom) margins for videocrop, giving an even-sized result (encoders need even sizes).
    ``crop`` is (x, y, w, h) in the source's pixels, or None for the whole frame."""
    W, H = size
    if crop is None:
        x, y, w, h = 0, 0, W, H
    else:
        x, y, w, h = crop
    x, y = max(0, min(int(x), W - 2)), max(0, min(int(y), H - 2))
    w, h = _even(min(int(w), W - x)), _even(min(int(h), H - y))
    w, h = max(2, w), max(2, h)
    return x, y, W - (x + w), H - (y + h)


def output_size(size, crop, fit=None):
    if fit:
        return max(2, _even(fit[0])), max(2, _even(fit[1]))
    l, t, r, b = crop_box(size, crop)
    return size[0] - l - r, size[1] - t - b


def _video_source(video, fps):
    """(chain that feeds the encoder, [extra stand-alone chains the pipeline needs])."""
    W, H = video["size"]
    kind = video.get("kind", "pipewire")
    if kind == "test":
        src = (f"videotestsrc name=vsrc is-live=true pattern=ball ! "
               f"video/x-raw,format=BGRx,width={W},height={H},framerate={fps}/1")
    else:
        opts = f"fd={video['fd']} " if video.get("fd") is not None else ""
        # keepalive re-sends the last frame when the screen is static, so the video has no gaps
        src = (f"pipewiresrc name=vsrc {opts}path={video['node']} always-copy=true do-timestamp=true "
               f"keepalive-time={max(1, int(1000 / fps))}")
    if video.get("window"):
        # the stream is read by Python (to cut the window out of the canvas) and handed to an appsrc
        fw, fh = output_size(video["size"], None, video["fit"])
        raw = "" if kind == "test" else " ! video/x-raw"          # (system memory; the test source is already raw)
        extra = [src + raw + " ! appsink name=wsink emit-signals=true sync=false async=false max-buffers=2 drop=true wait-on-eos=false"]
        head = ("appsrc name=wsrc is-live=true format=time do-timestamp=true block=false max-bytes=0 ! videoscale add-borders=true "
                f"method=bilinear ! video/x-raw,width={fw},height={fh},pixel-aspect-ratio=1/1")
        return head, extra
    if video.get("fit"):
        fw, fh = output_size(video["size"], None, video["fit"])
        return (src + f" ! videoconvert ! videoscale add-borders=true method=bilinear ! "
                f"video/x-raw,width={fw},height={fh},pixel-aspect-ratio=1/1"), []
    l, t, r, b = crop_box(video["size"], video.get("crop"))
    crop = f" ! videocrop left={l} top={t} right={r} bottom={b}" if (l or t or r or b) else ""
    return src + crop, []


def _video_encoder(fmt, quality, fps, out_h):
    q = QUALITY.get(quality, QUALITY["medium"])
    if fmt == "webm":
        return (f"vp8enc deadline=1 cpu-used=5 threads=8 end-usage=cq cq-level={q['vp8']} "
                f"target-bitrate=30000000 keyframe-max-dist={fps * 2}")
    preset = "superfast" if out_h > 1440 else "veryfast"          # 4K needs a faster preset to keep up in real time
    return (f"x264enc pass=quant quantizer={q['x264']} speed-preset={preset} bframes=0 key-int-max={fps * 2} "
            f"threads=0 ! video/x-h264,profile=high,stream-format=avc,alignment=au")


def _audio_source(a, idx):
    if a.get("kind") == "test":
        head = f"audiotestsrc is-live=true wave=sine freq={a.get('freq', 440.0)} volume=0.2"
    else:
        dev = a.get("device")
        dev_prop = f' device="{dev}"' if dev else ""
        head = f"pulsesrc{dev_prop} provide-clock=false do-timestamp=true buffer-time=200000 latency-time=20000"
    return (f"{head} ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! "
            f"queue max-size-time=5000000000 max-size-buffers=0 max-size-bytes=0 ! amix.")


def build_pipeline(video, audio, out_path, fmt="mp4", fps=30, quality="medium"):
    """The gst-launch style description of the whole recording pipeline (a string, nothing is started)."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    out_w, out_h = output_size(video["size"], video.get("crop"), video.get("fit"))
    # MP4 is written as fragments while recording (so a crash or a power cut still leaves a playable file) and
    # rewritten as an ordinary indexed MP4 when the recording is finished. Unbuffered, so what is written is on disk.
    mux = ('mp4mux name=mux fragment-duration=2000 fragment-mode=first-moov-then-finalise' if fmt == "mp4" else
           'webmmux name=mux') + f' ! filesink location="{out_path}" buffer-mode=unbuffered async=false'
    head, extra = _video_source(video, fps)
    vchain = (f"{head} ! videoconvert ! video/x-raw,format=I420 ! videorate ! "
              f"video/x-raw,framerate={fps}/1 ! queue name=vq max-size-time=3000000000 max-size-buffers=0 "
              f"max-size-bytes=0 ! {_video_encoder(fmt, quality, fps, out_h)} ! queue ! mux.")
    parts = [mux, vchain] + extra
    if audio:
        aenc = "avenc_aac bitrate=160000" if fmt == "mp4" else "opusenc bitrate=128000"
        parts.append(f"audiomixer name=amix ! audioconvert ! {aenc} ! queue ! mux.")
        parts += [_audio_source(a, i) for i, a in enumerate(audio)]
    return " ".join(parts)


# --------------------------------------------------------------------------- the recorder

class Recorder:
    """Records until stop(). Needs a running GLib main loop for the bus messages.

    on_done(path, error): called once, with the finished file's path (error None), or error text (path None).
    The file is written as ``<name>.part`` and renamed only after the container is finalised, so a half-written
    recording never looks like a finished one."""

    def __init__(self, video, audio, out_path, fmt="mp4", fps=30, quality="medium", on_done=None):
        ensure_gst()
        self.video, self.audio, self.fmt, self.fps, self.quality = video, list(audio), fmt, fps, quality
        self.final_path = out_path
        self.part_path = out_path + ".part"
        self.on_done = on_done or (lambda path, err: None)
        self.pipeline = None
        self.state = "idle"                    # idle -> recording -> stopping -> done | failed
        self.t_start = None
        self.warning = None                    # set when the file is usable but the recording ended early
        self._stop_timer = 0
        self._finished = False

    def description(self):
        return build_pipeline(self.video, self.audio, self.part_path, self.fmt, self.fps, self.quality)

    def start(self):
        if self.state != "idle":
            return
        folder = os.path.dirname(self.final_path) or "."
        try:
            os.makedirs(folder, exist_ok=True)
            if shutil.disk_usage(folder).free < MIN_FREE_BYTES:
                raise OSError("less than 300 MB of free disk space")
            self.pipeline = Gst.parse_launch(self.description())
        except (OSError, GLib.Error) as e:
            self._finish(None, f"Could not start recording: {getattr(e, 'message', e)}")
            return
        if self.video.get("window"):
            self._wsrc = self.pipeline.get_by_name("wsrc")
            self._wcaps = None
            wsink = self.pipeline.get_by_name("wsink")
            # (the sinks have async=false: with the default the pipeline waits for a first frame to reach the file before
            # it is "playing", while the appsink only reports samples once it is playing - a deadlock)
            wsink.connect("new-sample", lambda sink: self._window_sample(sink, "pull-sample"))
            wsink.connect("new-preroll", lambda sink: self._window_sample(sink, "pull-preroll"))
            wsink.connect("eos", lambda _s: GLib.idle_add(self._end_window_feed))
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
        self.pipeline.set_state(Gst.State.PLAYING)
        self.state = "recording"
        self.t_start = time.monotonic()

    def _end_window_feed(self):
        if getattr(self, "_wsrc", None) is not None:
            self._wsrc.end_of_stream()
        return False

    def _window_sample(self, sink, pull="pull-sample"):
        """Streaming thread: cut the window's rectangle out of the canvas frame and push it on. Following the crop
        hint of every frame is what makes a window that is resized keep recording correctly."""
        sample = sink.emit(pull)
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        st = sample.get_caps().get_structure(0)
        cw, ch, fmt = st.get_value("width"), st.get_value("height"), st.get_value("format")
        x, y, w, h = read_crop_meta(buf) or (0, 0, cw, ch)
        x, y = max(0, min(x, cw - 2)), max(0, min(y, ch - 2))
        w, h = max(2, min(w, cw - x)), max(2, min(h, ch - y))
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            stride = info.size // ch
            rows = np.frombuffer(info.data, dtype=np.uint8, count=ch * stride).reshape(ch, stride)
            data = rows[y:y + h, x * 4:(x + w) * 4].tobytes()                 # BGRA / BGRx: 4 bytes a pixel
        finally:
            buf.unmap(info)
        if self._wcaps != (w, h, fmt):
            self._wsrc.set_caps(Gst.Caps.from_string(f"video/x-raw,format={fmt},width={w},height={h},framerate=0/1"))
            self._wcaps = (w, h, fmt)
        self._wsrc.emit("push-buffer", Gst.Buffer.new_wrapped(data))
        return Gst.FlowReturn.OK

    @property
    def elapsed(self):
        return 0.0 if self.t_start is None else time.monotonic() - self.t_start

    def stop(self, timeout_s=10):
        """Finish the file: send end-of-stream so the muxer can write its index, then wait for it."""
        if self.state != "recording":
            return
        self.state = "stopping"
        self._send_eos()
        self._stop_timer = GLib.timeout_add(int(timeout_s * 1000), self._stop_timeout)

    def _send_eos(self):
        """End-of-stream into every real source (screen, microphone...). The window feeder's appsrc is left out: it
        is closed when the screen stream ends, and sending it EOS from here can deadlock against its own pushes."""
        it = self.pipeline.iterate_sources()
        while True:
            res, elem = it.next()
            if res == Gst.IteratorResult.OK:
                if elem.get_name() != "wsrc":
                    elem.send_event(Gst.Event.new_eos())
            elif res == Gst.IteratorResult.RESYNC:
                it.resync()
            else:
                break

    def stop_early(self, reason):
        """The source went away (screen locked, window closed...): finish what has been recorded so far."""
        if self.state == "recording":
            self.warning = reason
            self.stop(timeout_s=4)
            # a source that is already gone never passes the end-of-stream on, so push it into the video chain ourselves
            GLib.timeout_add(700, self._push_video_eos)

    def _push_video_eos(self):
        if self.state == "stopping" and self.pipeline is not None:
            src = self.pipeline.get_by_name("vsrc")
            pad = src.get_static_pad("src") if src is not None else None
            if pad is not None:
                pad.push_event(Gst.Event.new_eos())
            if self.video.get("window") and getattr(self, "_wsrc", None) is not None:
                self._wsrc.end_of_stream()
        return False

    def _stop_timeout(self):
        self._stop_timer = 0
        if self.warning:
            self._finish_incomplete()
        else:
            self._finish(None, "The recording did not finish cleanly (it timed out while saving)")
        return False

    def _on_message(self, _bus, msg):
        if msg.type == Gst.MessageType.EOS:
            if self.state == "recording":                      # the source ended by itself
                self.warning = self.warning or "The screen capture ended before you stopped the recording"
            self._finish(self.final_path, None)
        elif msg.type == Gst.MessageType.ERROR:
            err, _dbg = msg.parse_error()
            if self.state in ("recording", "stopping") and self._has_content():
                # keep what was recorded: try to close the file properly, else keep the fragments
                self.warning = self.warning or f"The recording ended early: {err.message}"
                if self.state == "recording":
                    self.state = "stopping"
                    self._send_eos()
                if not self._stop_timer:
                    self._stop_timer = GLib.timeout_add(4000, self._stop_timeout)
                elif self.state == "stopping":
                    pass
            else:
                self._finish(None, f"{err.message}")

    def _has_content(self):
        try:
            return os.path.getsize(self.part_path) > 4096
        except OSError:
            return False

    def _finish_incomplete(self):
        """EOS never arrived. The file is written in fragments, so what is on disk plays up to the last one."""
        stem, ext = os.path.splitext(self.final_path)
        path = f"{stem} (incomplete){ext}"
        self._finished_path_override = path
        self._finish(path, None)

    def _finish(self, path, error):
        if self._finished:
            return
        self._finished = True
        if self._stop_timer:
            GLib.source_remove(self._stop_timer)
            self._stop_timer = 0
        if self.pipeline is not None:
            bus = self.pipeline.get_bus()
            bus.remove_signal_watch()
            self.pipeline.set_state(Gst.State.NULL)
        if path and os.path.exists(self.part_path):
            try:
                os.replace(self.part_path, path)
            except OSError as e:
                path, error = None, f"Could not save the recording: {e}"
        elif os.path.exists(self.part_path) and error:
            try:
                os.remove(self.part_path)
            except OSError:
                pass
        self.state = "done" if path else "failed"
        self.on_done(path, error)


# --------------------------------------------------------------------------- inspecting a finished file

def probe_file(path, timeout_s=10):
    """{"duration": seconds, "video": [(codec, w, h, fps)], "audio": [(codec, channels, rate)]}."""
    ensure_gst()
    disc = GstPbutils.Discoverer.new(timeout_s * Gst.SECOND)
    info = disc.discover_uri(Gst.filename_to_uri(os.path.abspath(path)))
    out = {"duration": info.get_duration() / Gst.SECOND, "video": [], "audio": []}
    for s in info.get_video_streams():
        caps = s.get_caps().get_structure(0).get_name()
        out["video"].append((caps, s.get_width(), s.get_height(), s.get_framerate_num() / max(1, s.get_framerate_denom())))
    for s in info.get_audio_streams():
        out["audio"].append((s.get_caps().get_structure(0).get_name(), s.get_channels(), s.get_sample_rate()))
    return out


def audio_rms_db(path):
    """Loudness (dB RMS, 0 = full scale) of a recording's audio, to prove it is not silent. None if no audio."""
    ensure_gst()
    pipe = Gst.parse_launch(f'filesrc location="{path}" ! decodebin name=d d. ! audioconvert ! audio/x-raw,format=F32LE '
                            f'! level name=lv post-messages=true interval=100000000 ! fakesink sync=false')
    bus = pipe.get_bus()
    pipe.set_state(Gst.State.PLAYING)
    vals = []
    deadline = time.time() + 15
    while time.time() < deadline:
        m = bus.timed_pop_filtered(100 * Gst.MSECOND, Gst.MessageType.ELEMENT | Gst.MessageType.EOS | Gst.MessageType.ERROR)
        if m is None:
            continue
        if m.type in (Gst.MessageType.EOS, Gst.MessageType.ERROR):
            break
        s = m.get_structure()
        if s is not None and s.get_name() == "level":
            rms = s.get_value("rms")
            if rms:
                vals.append(sum(rms) / len(rms))
    pipe.set_state(Gst.State.NULL)
    return (sum(vals) / len(vals)) if vals else None


def count_video_frames(path, timeout_s=30):
    ensure_gst()
    pipe = Gst.parse_launch(f'filesrc location="{path}" ! decodebin ! videoconvert ! appsink name=s sync=false emit-signals=false')
    sink = pipe.get_by_name("s")
    pipe.set_state(Gst.State.PLAYING)
    n = 0
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        sample = sink.emit("try-pull-sample", 200 * Gst.MSECOND)
        if sample is not None:
            n += 1
        elif sink.get_property("eos"):
            break
    pipe.set_state(Gst.State.NULL)
    return n
