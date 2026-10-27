"""One way to turn uploaded photo bytes into pixels: EXIF orientation applied, exactly as a browser shows the photo.

Phones store most photos sideways and set the EXIF Orientation tag; browsers (and the web app's tap-to-point capture)
draw the photo rotated by that tag, so tap coordinates are in *oriented* pixels. Whether a decoder honours the tag
depends on the library, the flags and the version (`cv2.IMREAD_COLOR` does on OpenCV 5, `cv2.IMREAD_UNCHANGED` and a
plain `PIL.Image.open` do not), so every path that decodes a photo goes through `decode_bgr`, which ignores the
decoder's own handling and applies the tag itself.
"""

from __future__ import annotations

import io

import cv2
import numpy as np
from numpy.typing import NDArray

U8 = NDArray[np.uint8]
ORIENTATION_TAG = 0x0112


def exif_orientation(data: bytes) -> int:
    """The EXIF Orientation (1–8) of an encoded image; 1 when absent, unreadable or out of range."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            value = im.getexif().get(ORIENTATION_TAG, 1)
    except Exception:
        return 1
    try:
        o = int(value)
    except (TypeError, ValueError):
        return 1
    return o if 1 <= o <= 8 else 1


def orient(img: NDArray[np.generic], orientation: int) -> NDArray[np.generic]:
    """Stored pixels → displayed pixels for an EXIF orientation (the same transform as `PIL.ImageOps.exif_transpose`)."""
    if orientation == 2:
        out = img[:, ::-1]
    elif orientation == 3:
        out = img[::-1, ::-1]
    elif orientation == 4:
        out = img[::-1]
    elif orientation == 5:
        out = np.swapaxes(img, 0, 1)
    elif orientation == 6:
        out = np.swapaxes(img, 0, 1)[:, ::-1]  # 90° clockwise
    elif orientation == 7:
        out = np.swapaxes(img, 0, 1)[::-1, ::-1]
    elif orientation == 8:
        out = np.swapaxes(img, 0, 1)[::-1]  # 90° counter-clockwise
    else:
        out = img
    return np.ascontiguousarray(out)


def decode_bgr(data: bytes, *, gray: bool = False) -> U8:
    """Decode photo bytes to BGR (or grayscale) uint8 pixels in displayed orientation. ValueError if undecodable."""
    flags = (cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR) | cv2.IMREAD_IGNORE_ORIENTATION
    img = cv2.imdecode(np.frombuffer(data, np.uint8), flags)
    if img is None:
        raise ValueError("could not decode the image")
    return np.asarray(orient(img, exif_orientation(data)), dtype=np.uint8)


def oriented_size(data: bytes) -> tuple[int, int]:
    """(width, height) as displayed (EXIF orientation applied), without decoding the pixels."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
        o = im.getexif().get(ORIENTATION_TAG, 1)
    return (int(h), int(w)) if o in (5, 6, 7, 8) else (int(w), int(h))


__all__ = ["decode_bgr", "exif_orientation", "orient", "oriented_size"]
