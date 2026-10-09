"""Text recognition (OCR) for a captured region, using the Tesseract command-line program.

Tesseract is optional: without it the OCR mode explains how to install it (Debian/Ubuntu: ``tesseract-ocr``, plus
``tesseract-ocr-<language>`` for other languages). Nothing here touches the screen or the network; the picture is
written to a temporary file, recognised, and the file is deleted.

Screen text is small and often light on dark, which Tesseract reads poorly as it is, so the picture is prepared first:
enlarged, turned to grey, and inverted when the background is dark.
"""
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image

INSTALL_COMMAND = "sudo apt install tesseract-ocr"
INSTALL_HINT = f"Text recognition needs Tesseract. Install it with:  {INSTALL_COMMAND}"
MAX_SIDE = 7000


def tesseract_path():
    """The tesseract program, or None. SNIPSHOT_TESSERACT overrides the search (used by the tests)."""
    override = os.environ.get("SNIPSHOT_TESSERACT")
    if override:
        return override if os.access(override, os.X_OK) else None
    return shutil.which("tesseract")


def available():
    return tesseract_path() is not None


def languages():
    """Installed recognition languages, e.g. ['eng', 'fra']. Empty if Tesseract is missing."""
    exe = tesseract_path()
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln.strip() for ln in out.splitlines()[1:] if ln.strip() and ln.strip() != "osd"]


def prepare(arr):
    """BGRA array -> a grey PIL image that Tesseract reads well."""
    rgb = arr[..., 2::-1] if arr.shape[2] == 4 else arr[..., ::-1]               # BGR(A) -> RGB
    img = Image.fromarray(np.ascontiguousarray(rgb)).convert("L")
    w, h = img.size
    # Tesseract wants letters roughly 30 px tall; screen text is usually 10-20 px
    factor = 4 if h < 80 else 3 if h < 300 else 2 if h < 900 else 1
    factor = max(1, min(factor, MAX_SIDE // max(w, h, 1)))
    if factor > 1:
        img = img.resize((w * factor, h * factor), Image.LANCZOS)
    a = np.asarray(img)
    if a.mean() < 120:                                                            # light text on a dark background
        img = Image.fromarray(255 - a)
    border = 14
    padded = Image.new("L", (img.width + 2 * border, img.height + 2 * border), 255 if np.asarray(img).mean() > 127 else 0)
    padded.paste(img, (border, border))
    return padded


def clean(text):
    text = text.replace("\x0c", "")
    lines = [ln.rstrip() for ln in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _run(exe, path, lang, psm, timeout):
    p = subprocess.run([exe, path, "stdout", "-l", lang, "--psm", str(psm), "-c", "preserve_interword_spaces=1"],
                       capture_output=True, text=True, timeout=timeout)
    return clean(p.stdout), p.returncode, p.stderr.strip()


def recognize(arr, lang="eng", timeout=60):
    """Read the text in a BGRA image array. Returns (text, error): error is None on success (text may be empty when
    the picture has no text), otherwise a plain sentence. Runs a subprocess: call it off the GUI thread."""
    exe = tesseract_path()
    if not exe:
        return "", INSTALL_HINT
    img = prepare(arr)
    fd, path = tempfile.mkstemp(prefix="snipshot-ocr-", suffix=".png")
    os.close(fd)
    try:
        img.save(path)
        for psm in (6, 11):                      # a block of text, then scattered text if that found nothing
            text, rc, err = _run(exe, path, lang, psm, timeout)
            if rc != 0:
                if "Failed loading language" in err or "Error opening data file" in err:
                    return "", f"The text recognition language \"{lang}\" is not installed (sudo apt install tesseract-ocr-{lang})."
                return "", f"Text recognition failed: {err.splitlines()[-1] if err else 'unknown error'}"
            if text:
                return text, None
        return "", None
    except subprocess.TimeoutExpired:
        return "", "Text recognition took too long."
    except OSError as e:
        return "", f"Could not run Tesseract: {e}"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
