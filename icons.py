"""Original SVG artwork for Snipshot's tools and app icon (not copied from Greenshot or anyone else)."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

_HEAD = '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 24 24">'

TOOLS = {
    "select": _HEAD + '<path d="M5 3 L5 19 L9.5 14.8 L12.6 21 L15 19.9 L12 13.8 L18 13.6 Z" fill="#fff" stroke="#222" '
                      'stroke-width="1.5" stroke-linejoin="round"/></svg>',
    "rect": _HEAD + '<rect x="3.5" y="5.5" width="17" height="13" fill="none" stroke="#d62828" stroke-width="2.4"/></svg>',
    "ellipse": _HEAD + '<ellipse cx="12" cy="12" rx="9" ry="6.5" fill="none" stroke="#d62828" stroke-width="2.4"/></svg>',
    "line": _HEAD + '<path d="M4 19 L20 5" stroke="#d62828" stroke-width="2.6" stroke-linecap="round"/></svg>',
    "arrow": _HEAD + '<path d="M4 20 L16 8" stroke="#d62828" stroke-width="2.4" stroke-linecap="round"/>'
                     '<path d="M21 3 L21 13 L11 3 Z" fill="#d62828" transform="rotate(0)"/></svg>',
    "freehand": _HEAD + '<path d="M3 17 C6 7 8 7 10 13 S14 19 16 11 S19 6 21 8" fill="none" stroke="#d62828" '
                        'stroke-width="2.4" stroke-linecap="round"/></svg>',
    "text": _HEAD + '<path d="M5 5 H19 V8.5 M12 5 V19 M9 19 H15" fill="none" stroke="#222" stroke-width="2.4" '
                    'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "speech": _HEAD + '<path d="M5 4 H19 a2 2 0 0 1 2 2 V13 a2 2 0 0 1 -2 2 H12 L7 20 V15 H5 a2 2 0 0 1 -2 -2 V6 a2 2 0 0 1 '
                      '2 -2 Z" fill="#fff" stroke="#1d4ed8" stroke-width="1.9" stroke-linejoin="round"/></svg>',
    "step": _HEAD + '<circle cx="12" cy="12" r="9.2" fill="#8b0000"/><path d="M9.6 9.6 L12.4 7.8 V16.6" fill="none" '
                    'stroke="#fff" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "obfuscate": _HEAD + '<g><rect x="3" y="3" width="6" height="6" fill="#6b7280"/><rect x="9" y="3" width="6" height="6" '
                         'fill="#c4c9d1"/><rect x="15" y="3" width="6" height="6" fill="#8b929d"/>'
                         '<rect x="3" y="9" width="6" height="6" fill="#c4c9d1"/><rect x="9" y="9" width="6" height="6" '
                         'fill="#8b929d"/><rect x="15" y="9" width="6" height="6" fill="#6b7280"/>'
                         '<rect x="3" y="15" width="6" height="6" fill="#8b929d"/><rect x="9" y="15" width="6" height="6" '
                         'fill="#6b7280"/><rect x="15" y="15" width="6" height="6" fill="#c4c9d1"/></g></svg>',
    "highlight": _HEAD + '<rect x="3" y="12" width="18" height="7" fill="#ffee00"/><path d="M14 3 L20 9 L11 15 L8 12 Z" '
                         'fill="#444" stroke="#222" stroke-width="1" stroke-linejoin="round"/></svg>',
    "crop": _HEAD + '<path d="M7 2 V17 H22 M2 7 H17 V22" fill="none" stroke="#222" stroke-width="2.4" '
                    'stroke-linecap="square"/></svg>',
}

APP_ICON = """<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#34d399"/>
<stop offset="1" stop-color="#047857"/></linearGradient></defs>
<rect x="4" y="4" width="56" height="56" rx="13" fill="url(#g)"/>
<path d="M16 25 V16 H25 M39 16 H48 V25 M48 39 V48 H39 M25 48 H16 V39" fill="none" stroke="#fff"
 stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="32" cy="32" r="6.5" fill="#fff"/></svg>"""


def texture(svg):
    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(svg.encode()))


def image(svg, size=22):
    img = Gtk.Image.new_from_paintable(texture(svg))
    img.set_pixel_size(size)
    return img


def tool_image(name, size=22):
    return image(TOOLS[name], size)
