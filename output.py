"""Saving, clipboard and printing for Snipshot (the "destinations" in Greenshot's terms)."""
import os
import shutil
import subprocess

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

import imaging as im  # noqa: E402


def save_array(arr, path, fmt=None, quality=90):
    """Write the image. The format comes from the file extension unless ``fmt`` is given."""
    fmt = (fmt or os.path.splitext(path)[1].lstrip(".") or "png").lower()
    data = im.encode(arr, fmt, quality)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)               # never leaves a half-written screenshot behind
    return path


def copy_to_clipboard(arr):
    """Put the image on the clipboard as PNG. It stays available while Snipshot keeps running."""
    png = im.encode(arr, "png")
    display = Gdk.Display.get_default()
    provider = Gdk.ContentProvider.new_for_bytes("image/png", GLib.Bytes.new(png))
    display.get_clipboard().set_content(provider)
    return png


def copy_text(text):
    Gdk.Display.get_default().get_clipboard().set(text)


def read_clipboard_image(callback):
    """callback(array or None). Reads an image (or an image file) from the clipboard."""
    cb = Gdk.Display.get_default().get_clipboard()

    def done(clip, res):
        try:
            tex = clip.read_texture_finish(res)
            callback(im.decode_bytes(tex.save_to_png_bytes().get_data()) if tex else None)
        except GLib.Error:
            callback(None)
    cb.read_texture_async(None, done)


def clipboard_has_image():
    fmts = Gdk.Display.get_default().get_clipboard().get_formats()
    return fmts.contain_mime_type("image/png") or fmts.contain_mime_type("image/jpeg") \
        or fmts.contain_gtype(Gdk.Texture)


def open_path(path):
    Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)


def open_folder(path):
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    try:                                              # ask the file manager to highlight the file if it can
        Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None, "org.freedesktop.FileManager1",
                                       "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1", None) \
            .call_sync("ShowItems", GLib.Variant("(ass)", ([Gio.File.new_for_path(path).get_uri()], "")),
                       Gio.DBusCallFlags.NONE, 2000, None)
    except GLib.Error:
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(folder).get_uri(), None)


def email_attachment(path):
    exe = shutil.which("xdg-email")
    if exe:
        subprocess.Popen([exe, "--attach", path, "--subject", os.path.basename(path)])
        return True
    return False


def print_array(parent, arr, name="Screenshot"):
    """Standard GTK print dialog; the image is scaled to fit the page, keeping its shape."""
    surf = im.to_surface(arr)
    op = Gtk.PrintOperation()
    op.set_n_pages(1)
    op.set_job_name(name)
    op.set_unit(Gtk.Unit.POINTS)

    def draw_page(_op, ctx, _n):
        cr = ctx.get_cairo_context()
        pw, ph = ctx.get_width(), ctx.get_height()
        w, h = surf.get_width(), surf.get_height()
        s = min(pw / w, ph / h, 1.0 if w * 0.75 < pw and h * 0.75 < ph else 9e9)
        s = min(pw / w, ph / h)
        cr.translate((pw - w * s) / 2, 0)
        cr.scale(s, s)
        cr.set_source_surface(surf, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_BEST)
        cr.paint()
    op.connect("draw-page", draw_page)
    try:
        op.run(Gtk.PrintOperationAction.PRINT_DIALOG, parent)
    except GLib.Error:
        pass
