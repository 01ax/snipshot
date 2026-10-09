# Snipshot recording controls (GNOME Shell extension)

An optional extra for [Snipshot](../README.md). While Snipshot is recording the screen it adds, next to GNOME's own
orange "screen is being shared" button:

* a small orange pill (running time, then **pause / resume**, **stop and save**, **delete** buttons, each with a hover
  tooltip) that sits against GNOME's button so the two look like one control, and
* **Pause recording** and **Stop recording** tiles in the quick settings popup.

"Delete" moves the recording to the Trash, so a slip of the mouse is recoverable.

It talks to Snipshot over its D-Bus actions (`pause-recording`, `stop-recording`, `discard-recording`, and the
read-only states `recording-state` / `recording-time`, exported at `/local/snipshot`). Nothing leaves your computer.
It uses only GNOME's public extension interfaces and does not modify GNOME's own indicators; it is not needed to use
Snipshot (the tray menu and `snipshot record pause|stop|discard` do the same).

## Install

```
mkdir -p ~/.local/share/gnome-shell/extensions
cp -r shell-extension ~/.local/share/gnome-shell/extensions/snipshot-controls@01ax.github.io
gnome-extensions enable snipshot-controls@01ax.github.io
```

On Wayland a new extension is only picked up after you log out and back in.

Supported: GNOME Shell 50 (see `metadata.json`). Extensions depend on the shell's internal JavaScript, so other versions
may need a small adjustment; add the version to `shell-version` after testing it.

## Using it from another extension

`snipshotControls.js` is self-contained: `const c = new SnipshotControls(); c.enable(); ... c.disable();` (add the
rules in `stylesheet.css` to your extension's stylesheet).
