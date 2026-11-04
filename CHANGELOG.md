# Changelog

## 0.2.1

A smoother editor, true-pixel zoom, and a fix for recordings that came out as a slideshow on a busy desktop.

- **Editor: 100% is now real pixels.** On a scaled monitor (for example 150%) the editor used to show the capture
  magnified, which looked like a low-resolution copy. 100% / Actual size now puts one picture pixel on one screen pixel,
  Best fit no longer enlarges a small capture past that, the picture is placed on whole screen pixels, and the zoom
  box and Zoom in/out steps are in percent of actual pixels.
- **Editor: drawing and moving objects no longer lags.** The picture below the object you are dragging is rendered once
  per drag instead of on every mouse move, a picture shown smaller than its real size is drawn with a fast two-step
  scale instead of cairo's slow general filter, and big objects are no longer slow: the drop shadow's blur used to cost
  time in proportion to the object's area (a screen-sized rectangle took ~0.35 s per frame), now only along its outline
  (~10 ms). Highlight "dim outside" / "grey outside" are worked out once per drag, and Obfuscate "blur" is about 3x
  faster. Saved and copied images are unchanged.
- **Recording: commands to run before and after a recording** (`record_start_command` / `record_stop_command` in
  `config.json`). A desktop whose compositor is already busy (for example heavy blur effects on a 5K setup) cannot give
  the screen capture the frames it needs, and the video comes out as a slideshow even though the file says 60 fps. The
  start command runs, and is waited for, before the capture opens; the stop command runs after the recording has ended
  for any reason. Use them to switch such effects off for the duration.
- **Recording: 4K at 60 fps.** The colour conversion ran on one thread and the copy out of the capture buffer on the
  same one, which capped 4K recordings near 30 frames a second. They now run on separate threads and the conversion uses
  several.

## 0.2.0

Screen recording, text recognition and a lot of polish. First public release.

- **Screen recording** (Alt+Shift+R, or the Record tab in the capture overlay): a region, a whole screen or one
  window; system sound, microphone, both or neither; mouse pointer on or off; MP4 (H.264 + AAC) or WebM (VP8 + Opus);
  15-60 fps; countdown; pause / resume / stop / delete (to the Trash); crash-safe files; keeps the screen awake.
- **Copy text from the screen (OCR)**: press O in the capture overlay, drag over the text; needs Tesseract.
- **Capture overlay** switches between Screenshot (G), Record (R) and Text (O) with a top toolbar.
- Sharper preview after taking a screenshot; Ctrl+C in the editor copies the whole edited image.
- Tray menu with recording controls; `snipshot record pause|resume|stop|discard`; keyboard shortcut set-up in Preferences.
- Optional GNOME Shell extension with pause / stop / delete buttons beside GNOME's screen-sharing button.
- System audio no longer crackles (audio timestamps are left to the sound card's own clock).

## 0.1

Screenshot capture at native resolution on every monitor, destination picker, annotation editor (shapes, text,
arrows, step labels, highlight, pixelate and blur with adjustable strength, crop, resize, shadow, border, torn edge),
movable mouse-cursor object, zoom, delay, tray icon.
