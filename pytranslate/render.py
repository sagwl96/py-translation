"""Overlay text fitting: pick the largest font size at which a translation fits its source box."""
from PyQt6 import QtCore, QtGui

FONT_FAMILIES = ["Roboto", "Segoe UI", "Helvetica", "Arial", "DejaVu Sans", "sans-serif"]
MIN_PX = 8
# Source word-box height (text_h, ~cap height of the median word, ~0.77 of the CSS px size)
# -> overlay font pixel size. Calibrated on the synthetic page
# fixture so the English glyphs come out about as big as the German ones.
TEXT_H_TO_PX = 1.3
PAD = 1          # label inner padding (px)
GROW = 3         # label rect = source rect expanded by this many px per side
WIDTH_SLACK = 4   # px kept free horizontally: QLabel wraps a little earlier than QFontMetrics predicts
LINE_SLACK = 0.2  # word boxes exclude ascender/descender room: allow this x text_h extra height
_WRAP = QtCore.Qt.TextFlag.TextWordWrap


def make_font(px, family=None):
    f = QtGui.QFont()
    f.setFamilies([family] if family else FONT_FAMILIES)
    f.setPixelSize(max(1, int(px)))
    f.setWeight(QtGui.QFont.Weight.Medium)
    return f


def text_size(text, width, px, family=None):
    """(w, h) of `text` word-wrapped to `width` at `px`; w can exceed `width` for a long word."""
    fm = QtGui.QFontMetrics(make_font(px, family))
    br = fm.boundingRect(QtCore.QRect(0, 0, max(1, int(width)), 100000), int(_WRAP), text)
    return br.width(), br.height()


def fits(text, width, height, px, family=None):
    w, h = text_size(text, width, px, family)
    return w <= width and h <= height


def fit_font_px(text, width, height, start_px, family=None, min_px=MIN_PX):
    """Largest integer pixel size <= start_px (but >= min_px) at which `text` fits
    width x height with word wrap. Returns min_px when nothing fits (see elide_to_fit)."""
    px = max(int(round(start_px)), min_px)
    while px > min_px and not fits(text, width, height, px, family):
        px -= 1
    return px


def elide_to_fit(text, width, height, px, family=None):
    """Drop trailing words until `text` + "…" fits; returns text unchanged if it already fits."""
    if fits(text, width, height, px, family):
        return text
    words = text.split()
    while len(words) > 1:
        words.pop()
        cand = " ".join(words) + "…"
        if fits(cand, width, height, px, family):
            return cand
    return words[0] if words else text   # nothing fits: keep the first word (clipped)


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb1, rgb2):
    a, b = luminance(rgb1), luminance(rgb2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


DARK_TEXT = (17, 17, 17)
LIGHT_TEXT = (255, 255, 255)
DEFAULT_BG = (252, 250, 222)


def pick_text_color(bg):
    """Black-ish or white text, whichever contrasts more (WCAG ratio) with `bg` (r, g, b)."""
    return DARK_TEXT if contrast_ratio(bg, DARK_TEXT) >= contrast_ratio(bg, LIGHT_TEXT) else LIGHT_TEXT


MIN_SIDE = 6   # a rect is not shrunk below this many px on the cut axis; the cut is shared instead


def _overlap(a, b):
    ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return ox, oy


def _contains(a, b):
    return (a[0] <= b[0] and a[1] <= b[1] and a[0] + a[2] >= b[0] + b[2] and a[1] + a[3] >= b[1] + b[3])


def _split(a, b, axis):
    """Separate two overlapping rects along axis (0=x, 1=y). `b` is the later one (in reading
    order): normally only b shrinks away from a; if that would leave it thinner than MIN_SIDE,
    both are cut at the middle of the overlap."""
    a, b = list(a), list(b)
    s = 2 + axis                      # size index
    a_end = a[axis] + a[s]
    b_end = b[axis] + b[s]
    if b[axis] >= a[axis]:            # b starts at/after a: cut b's near edge to a's far edge
        new_b = b_end - a_end
        if new_b >= MIN_SIDE:
            b[axis], b[s] = a_end, new_b
        else:
            mid = (b[axis] + a_end) // 2
            a[s] = max(1, mid - a[axis])
            b[s] = b_end - mid
            b[axis] = mid
    else:                             # b starts before a: cut b's far edge back to a's start
        new_b = a[axis] - b[axis]
        if new_b >= MIN_SIDE:
            b[s] = new_b
        else:
            mid = (a[axis] + b_end) // 2
            b[s] = max(1, mid - b[axis])
            a[s] = a_end - mid
            a[axis] = mid
    return tuple(a), tuple(b)


def resolve_overlaps(rects, max_passes=20):
    """Shrink rects (x, y, w, h) so that no two intersect. Rects are processed in reading
    order; for each overlapping pair the later one shrinks away from the overlap along the axis
    where the overlap is thinner (or both are cut at the overlap middle if that would leave the
    later one too thin). Identical rects are split in half. A rect completely inside another cannot be separated: it becomes
    (x, y, 0, 0), i.e. hidden. Returns a new list in the input order."""
    out = [tuple(r) for r in rects]
    order = sorted(range(len(out)), key=lambda i: (out[i][1], out[i][0]))
    for _ in range(max_passes):
        changed = False
        for ii, i in enumerate(order):
            for j in order[ii + 1:]:
                a, b = out[i], out[j]
                if a[2] <= 0 or b[2] <= 0:
                    continue
                ox, oy = _overlap(a, b)
                if ox <= 0 or oy <= 0:
                    continue
                if _contains(a, b) and _contains(b, a):   # identical: share the area, both clipped
                    axis = 1 if a[3] >= 2 * MIN_SIDE else 0
                    sz = 2 + axis
                    half = a[sz] // 2
                    first, second = list(a), list(a)
                    first[sz] = max(1, half)
                    second[axis] = a[axis] + half
                    second[sz] = a[sz] - half
                    out[i], out[j] = tuple(first), tuple(second)
                elif _contains(a, b) or _contains(b, a):
                    k = j if _contains(a, b) else i
                    out[k] = (out[k][0], out[k][1], 0, 0)
                else:
                    out[i], out[j] = _split(a, b, 1 if oy <= ox else 0)
                changed = True
        if not changed:
            break
    return out
