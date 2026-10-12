"""Screen-capture helpers: QImage conversion and coordinate scaling."""
import cv2
import numpy as np
from PyQt6 import QtGui


def qimage_to_bgr(qimage):
    """Convert any QImage to a BGR uint8 numpy array (honours bytesPerLine)."""
    qimage = qimage.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    w, h, bpl = qimage.width(), qimage.height(), qimage.bytesPerLine()
    buf = np.frombuffer(qimage.constBits().asstring(bpl * h), np.uint8).reshape(h, bpl)
    rgba = buf[:, :w * 4].reshape(h, w, 4)
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)


def scale_rects(rects, dpr):
    """Convert device-pixel rects (x, y, w, h) to logical pixels by dividing by dpr."""
    if not dpr or dpr == 1:
        return [tuple(r) for r in rects]
    return [tuple(int(round(v / dpr)) for v in r) for r in rects]


def bgr_to_qimage(bgr):
    """Convert a BGR uint8 numpy array to an independent RGB32 QImage."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QtGui.QImage(rgb.data, w, h, w * 3, QtGui.QImage.Format.Format_RGB888).convertToFormat(
        QtGui.QImage.Format.Format_RGB32)


def sample_background(img_bgr, rect, ring=3, gap=1):
    """Median colour (r, g, b) of a `ring`-px band `gap` px outside rect (x, y, w, h), in
    image pixels, clipped to the image. None if the band is entirely outside the image."""
    ih, iw = img_bgr.shape[:2]
    x, y, w, h = rect
    o = gap + ring
    x0, y0, x1, y1 = (max(0, x - o), max(0, y - o), min(iw, x + w + o), min(ih, y + h + o))
    if x1 <= x0 or y1 <= y0:
        return None
    mask = np.ones((y1 - y0, x1 - x0), bool)
    ix0, iy0, ix1, iy1 = (max(0, x - gap) - x0, max(0, y - gap) - y0,
                          min(iw, x + w + gap) - x0, min(ih, y + h + gap) - y0)
    mask[max(0, iy0):max(0, iy1), max(0, ix0):max(0, ix1)] = False
    px = img_bgr[y0:y1, x0:x1][mask]
    if len(px) == 0:
        return None
    b, g, r = np.median(px, axis=0)
    return int(r), int(g), int(b)
