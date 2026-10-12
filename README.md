# Snipshot

Screenshots with an annotation editor, screen recording, and "copy the text from this part of the screen" (OCR), for
**GNOME on Wayland**. Press a shortcut, drag a rectangle, and decide what to do with it.

Its workflow is modelled on [Greenshot](https://getgreenshot.org/) (a Windows tool): capture, then a destination menu,
then a proper editor. Snipshot is an independent project; it contains none of Greenshot's code and is not affiliated
with it.

> Status: young, used daily on Ubuntu 26.04 with GNOME 50 (two monitors, one scaled 1.5x). Other GNOME versions and
> distributions are untested; please open an issue if something misbehaves. X11 sessions and other desktops are not
> supported.

## What it does

**Screenshots**
- Region, whole screen, last region, or a window. Every monitor is captured at its **real pixels** (a 1.5x monitor is
  not blown up or shrunk), with no shutter sound and no flash.
- The mouse pointer is captured as its own movable object, so you can move it, send it behind other objects, or delete it.
- After capturing you choose what to do (editor, clipboard, save, save as, print, e-mail), like Greenshot. Closing the
  menu discards the capture. You can also fix the destinations in Preferences.
- Optional delay (`snipshot --delay 5 region`, or "in 3 / 5 seconds" in the tray menu).

**Editor**
- Rectangle, ellipse, line, arrow, freehand, text (the box hugs what you type), speech bubble, numbered step labels,
  highlight, **pixelate and blur with adjustable strength**, crop, resize, canvas size, border, shadow, torn edge,
  brightness, contrast and gamma.
- Tools stay active until you pick Select again; right-click gives the object menu (arrange, duplicate, stretch to
  the edge...); Ctrl+wheel zooms around the pointer; undo and redo.
- Ctrl+C copies the whole image with your edits; Ctrl+Shift+C copies just the selected objects.

**Screen recording**
- A region, a whole screen, or one window. System sound, microphone, both, or neither. Mouse pointer on or off.
- MP4 (H.264 + AAC) or WebM (VP8 + Opus), 15 to 60 frames per second, three quality levels, optional countdown.
- Pause, resume, stop and save, or delete (to the Trash). Files are written so that a crash or power cut still
  leaves a playable video. The screen is kept awake while recording.
- The tray icon turns red while recording (amber while paused) and its menu has the controls. An optional GNOME Shell
  extension puts the same controls next to GNOME's own screen-sharing button (see [`shell-extension/`](shell-extension/)).

**Text from the screen (OCR)**
- Press **O** in the capture overlay and drag over some text. A small window shows what was read and it is copied
  to the clipboard. Uses [Tesseract](https://github.com/tesseract-ocr/tesseract) (optional).

## Install

Ubuntu / Debian (GNOME on Wayland):

```
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-gst-plugins-base-1.0 \
    python3-numpy python3-pil \
    gstreamer1.0-pipewire gstreamer1.0-plugins-good gstreamer1.0-plugins-ugly gstreamer1.0-libav \
    xdg-desktop-portal-gnome
sudo apt install tesseract-ocr        # optional: copy text from the screen (add tesseract-ocr-<lang> for other languages)

git clone https://github.com/01ax/snipshot
cd snipshot
python3 install.py                     # per-user install; no root needed
snipshot --daemon                      # starts in the background with a tray icon
```

`install.py` copies Snipshot to `~/.local/share/snipshot`, adds the launcher `~/.local/bin/snipshot` (make sure that
folder is on your `PATH`), the icon and an application menu entry. `python3 install.py --uninstall` removes it again
(your settings in `~/.config/snipshot` are left alone). Your desktop needs a tray host to show the tray icon (Ubuntu's
AppIndicator extension provides one); everything also works from the keyboard without it.

**Shortcuts.** GNOME apps cannot claim global shortcuts themselves, so open Snipshot's Preferences, **General**, and
click **Set up the shortcuts**. That adds Alt+Shift+G (capture) and Alt+Shift+R (record) as ordinary GNOME custom
shortcuts; it never replaces another program's shortcut. You can also bind `snipshot region` and `snipshot record`
yourself in GNOME Settings, Keyboard.

## Using it

In the capture overlay (Alt+Shift+G):

| Key | Does |
|---|---|
| drag | choose a region |
| Enter | use this whole screen |
| **G** / **R** / **O** | Screenshot / Record / Text (OCR) mode (also the buttons at the top) |
| A / V | (record mode) system sound / microphone on or off |
| M | mouse pointer on or off |
| Z | magnifier |
| Esc | cancel |

Command line (`snipshot --help` lists everything):

```
snipshot region                  capture a region          snipshot record               open the overlay in record mode
snipshot fullscreen [SCREEN]     capture the desktop       snipshot record screen [NAME] record a whole screen
snipshot window                  capture a window          snipshot record window        record one window
snipshot ocr                     copy text from the screen snipshot record pause|stop|discard
snipshot FILE                    open an image to edit     snipshot prefs / --quit / --version
```

Pressing the record shortcut (or `snipshot record`) again while recording stops and saves it.

Screenshots go to `~/Pictures/Screenshots` and recordings to `~/Videos/Screencasts`; both folders, the file names and
every other option are in Preferences. Settings live in `~/.config/snipshot/config.json`.

## Good to know

- **Privacy.** Everything stays on your computer. Recording uses GNOME's own screen-capture interface, so GNOME
  shows its orange "screen is being shared" indicator while you record. That is deliberate and cannot be turned off.
- **Locking the screen ends a recording** (GNOME closes the capture); what was recorded until then is kept.
- GNOME's window picker (for "record one window") is the desktop's own dialog.
- Recording a 4K screen at 30 fps uses roughly one and a half CPU cores; lower the frame rate or quality in
  Preferences on a slower machine.
- Not implemented (yet): Greenshot's cut marks, emoji and icon objects, and online destinations such as Imgur or Office.

## How it works

Screen frames come from Mutter's `org.gnome.Mutter.ScreenCast` interface over PipeWire (windows are chosen through
the desktop portal), are read with GStreamer, and a recording is encoded to MP4 or WebM by a GStreamer pipeline.
The UI is GTK 4 with PyGObject; images are handled with NumPy and Pillow; text recognition runs the `tesseract`
program. See the code comments for the reasoning behind the less obvious parts (they record several hard-won
details of GNOME, PipeWire and GStreamer behaviour).

## Development

The interactive tests (overlay, recording, tray, OCR...) run inside a **private, invisible GNOME session** with a
virtual monitor and virtual audio devices, so they never touch your screens, speakers, microphone or settings:

```
sudo apt install bubblewrap gnome-shell pipewire wireplumber pipewire-pulse   # once
tests/run_all.sh          # everything (several minutes)
tests/run_all.sh quick    # without the recording tests
tools/headless_session.sh python3 -I tests/test_overlay_modes.py   # one test
```

`SNIPSHOT_CHANNEL=dev` (or `python3 install.py --dev`) runs a side-by-side copy with its own settings and application
id, which is handy for trying changes without touching your normal install.

## Licence

[MIT](LICENSE). Snipshot runs GStreamer, PipeWire and Tesseract as separate libraries/programs; they keep their own licences.
