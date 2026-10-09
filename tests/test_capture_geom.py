import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import capture as C
fails = 0
def check(n, ok, extra=""):
    global fails; fails += 0 if ok else 1; print(("PASS" if ok else "FAIL"), "-", n, extra)

# the user's real layout: DP-2 2560x1440 @1.0 at x=0, DP-4 logical 2560x1440 at x=2560 (4K panel at 1.5)
layout = [(0, 0, 2560, 1440), (2560, 0, 2560, 1440)]
# Mutter composites the portal screenshot at the highest scale (1.5): 7680 x 2160
x0, y0, sx, sy = C.image_scale(7680, 2160, layout)
check("scale 1.5 detected from image vs logical size", (x0, y0, round(sx, 3), round(sy, 3)) == (0, 0, 1.5, 1.5))
check("rect on monitor 2 maps into the right half", C.logical_to_image((2560 + 100, 200, 400, 300), (x0, y0, sx, sy), 7680, 2160) == (3990, 300, 600, 450))
check("rect clamped to the image", C.logical_to_image((5000, 1300, 500, 500), (x0, y0, sx, sy), 7680, 2160) == (7500, 1950, 180, 210))
# if the portal instead returns logical size (5120 x 1440)
x0, y0, sx, sy = C.image_scale(5120, 1440, layout)
check("1.0 scale image", (round(sx, 3), round(sy, 3)) == (1.0, 1.0) and C.logical_to_image((10, 20, 30, 40), (x0, y0, sx, sy), 5120, 1440) == (10, 20, 30, 40))
# a layout whose origin is not 0 (monitor to the left)
lay2 = [(-1920, 0, 1920, 1080), (0, 0, 2560, 1440)]
x0, y0, sx, sy = C.image_scale(4480, 1440, lay2)
check("negative origin handled", x0 == -1920 and C.logical_to_image((-1920, 0, 100, 100), (x0, y0, sx, sy), 4480, 1440) == (0, 0, 100, 100))

# ---- native-pixel mapping used by the new per-monitor selector
import numpy as np
import screencast as SCN
info = SCN.MonitorInfo("DP-4", 2560, 0, 2560, 1440, 1.5, 3840, 2160)
check("logical rect on the 1.5x monitor -> real pixels", C.logical_to_native((100, 200, 400, 300), info, 3840, 2160) == (150, 300, 600, 450))
check("selection past the edge is clamped to the monitor", C.logical_to_native((2400, 1300, 500, 500), info, 3840, 2160) == (3600, 1950, 240, 210))
info1 = SCN.MonitorInfo("DP-2", 0, 0, 2560, 1440, 1.0, 2560, 1440)
check("1.0x monitor is a 1:1 mapping (no upscale)", C.logical_to_native((10, 20, 30, 40), info1, 2560, 1440) == (10, 20, 30, 40))
sprite = np.zeros((28, 18, 4), np.uint8)
shot = SCN.MonitorShot(info, np.zeros((2160, 3840, 4), np.uint8), (sprite, 2850, 1582))
r = C.cursor_in_region(shot, (2800, 1500, 200, 200))
check("cursor inside the region is placed relative to it", r is not None and r[1:] == (50, 82))
check("cursor outside the region is dropped", C.cursor_in_region(shot, (0, 0, 200, 200)) is None)
check("cursor partly inside is kept", C.cursor_in_region(shot, (2860, 1590, 100, 100)) is not None)
check("no cursor -> None", C.cursor_in_region(SCN.MonitorShot(info, shot.array), (0, 0, 10, 10)) is None)
print("\nFAILED" if fails else "\nALL PASSED", fails or "")
sys.exit(1 if fails else 0)
