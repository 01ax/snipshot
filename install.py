#!/usr/bin/env python3
"""Install Snipshot for the current user: modules, launcher, icon and menu entry. Safe to re-run."""
import os, shutil, stat, sys
HERE = os.path.dirname(os.path.abspath(__file__))
MODULES = ["app.py", "canvas.py", "capture.py", "config.py", "cursors.py", "dialogs.py", "editor.py", "effects.py",
           "icons.py", "imaging.py", "model.py", "output.py", "picker.py", "prefs.py", "render.py", "screencast.py", "tray.py"]
home = os.path.expanduser("~")
target = os.path.join(home, ".local/share/snipshot")
os.makedirs(target, exist_ok=True)
for m in MODULES:
    shutil.copy2(os.path.join(HERE, m), os.path.join(target, m))
os.makedirs(os.path.join(home, ".local/bin"), exist_ok=True)
launcher = os.path.join(home, ".local/bin/snipshot")
with open(launcher, "w") as fh:
    fh.write(f'#!/bin/sh\n'
             f'# GTK\'s software (cairo) renderer on purpose: the OpenGL renderer stalled every window on this machine when the\n'
             f'# NVIDIA GPU memory was nearly full (frozen crosshair), and the Vulkan renderer crashes the full-screen overlay.\n'
             f'export GSK_RENDERER="${{GSK_RENDERER:-cairo}}"\nexec python3 "{target}/app.py" "$@"\n')
os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
sys.path.insert(0, HERE)
import icons
icon_dir = os.path.join(home, ".local/share/icons/hicolor/scalable/apps")
os.makedirs(icon_dir, exist_ok=True)
open(os.path.join(icon_dir, "snipshot.svg"), "w").write(icons.APP_ICON)
apps = os.path.join(home, ".local/share/applications")
os.makedirs(apps, exist_ok=True)
open(os.path.join(apps, "local.snipshot.desktop"), "w").write(
"""[Desktop Entry]
Type=Application
Name=Snipshot
GenericName=Screenshot tool
Comment=Capture and annotate screenshots (pixelate, blur, arrows, text...)
Exec=snipshot --daemon
Icon=snipshot
Terminal=false
Categories=Graphics;Utility;
StartupNotify=false
Actions=region;fullscreen;lastregion;

[Desktop Action region]
Name=Capture region
Exec=snipshot region

[Desktop Action fullscreen]
Name=Capture full screen
Exec=snipshot fullscreen

[Desktop Action lastregion]
Name=Capture last region
Exec=snipshot lastregion
""")
os.system("update-desktop-database ~/.local/share/applications 2>/dev/null; gtk-update-icon-cache -q -t ~/.local/share/icons/hicolor 2>/dev/null")
print("installed to", target)
