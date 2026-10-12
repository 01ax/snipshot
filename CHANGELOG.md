# Changelog

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
