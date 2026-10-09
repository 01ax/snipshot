#!/usr/bin/env python3
"""Install Snipshot for the current user (nothing needs root). Safe to re-run.

    python3 install.py            the normal install:  ~/.local/share/snipshot,     ~/.local/bin/snipshot
    python3 install.py --dev      a side-by-side copy: ~/.local/share/snipshot-dev, ~/.local/bin/snipshot-dev
    python3 install.py --uninstall [--dev]

The dev copy has its own application id, settings folder, tray icon and menu entry, so it can run next to the normal
install without touching it. It never changes keyboard shortcuts by itself.
"""
import glob
import os
import shutil
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
dev = "--dev" in sys.argv
name = "snipshot-dev" if dev else "snipshot"
app_id = "local.snipshot.dev" if dev else "local.snipshot"
title = "Snipshot (dev)" if dev else "Snipshot"
home = os.path.expanduser("~")
data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local/share")
target = os.path.join(data_home, name)
launcher = os.path.join(home, ".local/bin", name)
apps = os.path.join(data_home, "applications")
desktop = os.path.join(apps, f"{app_id}.desktop")
icon_dir = os.path.join(data_home, "icons/hicolor/scalable/apps")

if "--uninstall" in sys.argv:
    for path in (launcher, desktop):
        if os.path.exists(path):
            os.remove(path)
    shutil.rmtree(target, ignore_errors=True)
    if not dev:
        for f in ("snipshot.svg", "snipshot-recording.svg", "snipshot-paused.svg"):
            p = os.path.join(icon_dir, f)
            if os.path.exists(p):
                os.remove(p)
    print(f"removed {title} (settings in ~/.config/{name} were left alone)")
    sys.exit(0)

modules = sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "*.py")) if os.path.basename(p) != "install.py")
os.makedirs(target, exist_ok=True)
for stale in glob.glob(os.path.join(target, "*.py")):
    if os.path.basename(stale) not in modules:
        os.remove(stale)
for m in modules:
    shutil.copy2(os.path.join(HERE, m), os.path.join(target, m))

os.makedirs(os.path.dirname(launcher), exist_ok=True)
channel = "export SNIPSHOT_CHANNEL=dev\n" if dev else ""
with open(launcher, "w") as fh:
    fh.write("#!/bin/sh\n"
             "# GTK's software (cairo) renderer on purpose: the OpenGL renderer stalled every window on a machine whose GPU memory\n"
             "# was nearly full (frozen crosshair), and the Vulkan renderer crashes the full-screen overlay.\n"
             f'{channel}export GSK_RENDERER="${{GSK_RENDERER:-cairo}}"\nexec python3 "{target}/app.py" "$@"\n')
os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

sys.path.insert(0, HERE)
import icons  # noqa: E402

# The dev copy keeps its icons in its own folder (the app writes them there itself); the normal install shares the theme.
if not dev:
    os.makedirs(icon_dir, exist_ok=True)
    for fname, svg in (("snipshot.svg", icons.APP_ICON), ("snipshot-recording.svg", icons.RECORDING_ICON),
                       ("snipshot-paused.svg", icons.PAUSED_ICON)):
        with open(os.path.join(icon_dir, fname), "w") as fh:
            fh.write(svg)

os.makedirs(apps, exist_ok=True)
with open(desktop, "w") as fh:
    fh.write(f"""[Desktop Entry]
Type=Application
Name={title}
GenericName=Screenshot and screen recording tool
Comment=Capture and annotate screenshots, record the screen
Exec={launcher} --daemon
Icon=snipshot
Terminal=false
Categories=Graphics;Utility;
StartupNotify=false
Actions=region;record;fullscreen;lastregion;

[Desktop Action region]
Name=Capture region
Exec={launcher} region

[Desktop Action record]
Name=Record the screen
Exec={launcher} record

[Desktop Action fullscreen]
Name=Capture full screen
Exec={launcher} fullscreen

[Desktop Action lastregion]
Name=Capture last region
Exec={launcher} lastregion
""")
for cmd in (["update-desktop-database", apps], ["gtk-update-icon-cache", "-q", "-t", os.path.join(data_home, "icons/hicolor")]):
    try:
        subprocess.run(cmd, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass
print(f"installed {title} to {target}")
print(f"start it with:  {launcher} --daemon      record with:  {launcher} record")
