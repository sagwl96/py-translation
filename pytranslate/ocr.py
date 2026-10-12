"""Tesseract OCR and image preprocessing.

All functions take the downscale factor explicitly (`scale_factor`): rects are
reported in the coordinates of the original capture.
"""
import atexit
import glob
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import tesserocr

from . import mt
from .config import CONFIG

MIN_STRIP_HEIGHT = 150   # px of the OCRed image per strip
MAX_STRIPS = 6


class OcrError(RuntimeError):
    """OCR could not run at all (e.g. language data missing); shown to the user."""


def preprocess_image(img):
    """Downscale captures wider than max_ocr_width. Returns (image, scale_factor)."""
    if CONFIG.max_ocr_width <= 0:
        return img, 1.0
    h, w = img.shape[:2]
    if w > CONFIG.max_ocr_width:
        scale_factor = CONFIG.max_ocr_width / w
        new_w = int(w * scale_factor)
        new_h = int(h * scale_factor)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA), scale_factor
    return img, 1.0


def estimate_glyph_height(img):
    """Median height (px) of the connected components of the ink, ~6 ms on 1400x700.

    Ink comes from a local (adaptive) threshold, so text on coloured buttons/bars counts;
    light-on-dark text works too. Returns 0.0 if nothing was found.
    """
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = _ink_mask(gray)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    h = stats[1:, cv2.CC_STAT_HEIGHT]
    w = stats[1:, cv2.CC_STAT_WIDTH]
    keep = (h >= 2) & (h <= w * 4 + 4) & (w <= h * 4 + 4)   # glyph-like blobs, not rules/specks
    return float(np.median(h[keep])) if keep.any() else 0.0


def perform_ocr(img, scale_factor=1.0):
    """One Tesseract pass (per strip). Text whose estimated glyph height (in original capture
    pixels) is below min_glyph_height is upscaled x ocr_upscale first (INTER_CUBIC).
    Rects are reported in the coordinates of the original capture."""
    base = scale_factor
    if estimate_glyph_height(img) / base < CONFIG.min_glyph_height:
        img = cv2.resize(img, None, fx=CONFIG.ocr_upscale, fy=CONFIG.ocr_upscale,
                         interpolation=cv2.INTER_CUBIC)
        base *= CONFIG.ocr_upscale
    lines = _page_pass(img, base)
    if _poor(lines):   # nothing found, or shaky: retry once with normalised variants
        lines = _fallback_pass(img, base, lines)
    return lines


FALLBACK_MIN_CONF = 50


def _poor(lines):
    return not lines or mean_conf(lines) < FALLBACK_MIN_CONF


def mean_conf(lines):
    """Character-weighted mean word confidence of OCR lines."""
    n = sum(len(l['text']) for l in lines)
    return sum(l.get('conf', 100.0) * len(l['text']) for l in lines) / n if n else 0.0


def score(lines):
    """Sum of confidence x text length: higher = more text read more confidently."""
    return sum(l.get('conf', 100.0) * len(l['text']) for l in lines)


def _page_pass(img, base):
    lines = ocr_strips(img, base)
    kept, extra = ocr_solid_regions(img, lines, base)
    return kept + extra


def _fallback_pass(img, base, first):
    """Second chance for captures the normal pass could not read: contrast-normalised (CLAHE),
    x2 upscaled, then its inversion (light text on dark). Keeps the best-scoring result."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    up = CONFIG.ocr_upscale
    gray = cv2.resize(gray, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC)
    best = first
    for variant in (gray, 255 - gray):
        cand = _page_pass(cv2.cvtColor(variant, cv2.COLOR_GRAY2BGR), base * up)
        if score(cand) > score(best):
            best = cand
        if not _poor(best):
            break
    return best


# --- text on coloured buttons / header bars ------------------------------------------------
# A solid coloured box on a white page can lose its text in the full-page pass (small text,
# low contrast against the box once the page binarisation is decided). Each box is cropped and OCRed again
# on an upscale; that result replaces the page pass's lines inside the box if it read more.
MIN_BOX_W, MIN_BOX_H = 40, 16
REGION_PAD = 4
REGION_STRIP_BASE = 100   # block-id namespace of region passes (strip ids of the page pass are small)


def find_solid_regions(img):
    """Bounding boxes (x, y, w, h) of solid, non-background coloured rectangles (buttons,
    header bars) in a BGR image. The background is the most common colour. Works on a
    half-size copy (INTER_AREA) to stay cheap on big captures.

    Each frequent non-background colour is masked on its own, so a bar whose edges touch
    a card's dark border lines is not merged with them into one sparse shape (which then
    failed the fill test and was skipped)."""
    f = max(1, round(img.shape[1] / 300))   # boxes are >= 40x16 px, so ~300 px wide is plenty
    small = cv2.resize(img, None, fx=1 / f, fy=1 / f, interpolation=cv2.INTER_AREA) if f > 1 else img
    q = (small >> 4).astype(np.uint16)
    packed = (q[..., 0] << 8) | (q[..., 1] << 4) | q[..., 2]
    counts = np.bincount(packed.ravel(), minlength=4096)
    bg_bin = counts.argmax()
    bg = small[packed == bg_bin].mean(axis=0)
    ih, iw = packed.shape
    min_px = max(1, (MIN_BOX_W // f) * (MIN_BOX_H // f) // 2)
    boxes = []
    for b in np.argsort(counts)[::-1][:1 + MAX_COLOURS]:
        if counts[b] < min_px:
            break
        colour = small[packed == b].mean(axis=0)
        if b == bg_bin or np.abs(colour - bg).max() <= 30:
            continue
        # colour match via a 4096-entry lookup on the quantised bins (bin centres)
        near = _BIN_LUT_DIST(colour)[packed]
        # close small holes (the glyphs drawn on the bar) so the bar stays one component
        joined = cv2.morphologyEx(near, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
        for i in range(1, n):
            x, y, w, h, _ = stats[i]
            if w * f < MIN_BOX_W or h * f < MIN_BOX_H or w * h > 0.5 * iw * ih:
                continue
            # fill is measured on the un-closed mask: a bar with text is mostly bar colour,
            # a word of dark text is not
            if near[y:y + h, x:x + w][labels[y:y + h, x:x + w] == i].mean() < 0.6:
                continue
            box = (int(x * f), int(y * f), int(w * f), int(h * f))
            if not any(_iou(box, o) > 0.5 for o in boxes):
                boxes.append(box)
    # A box that contains another one is a panel (e.g. a card around its header bar), not a
    # button: re-reading it would duplicate the inner box's text.
    return [b for b in boxes if not any(o is not b and _contains(b, o) for o in boxes)]


def _contains(a, b, slack=2):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (bx >= ax - slack and by >= ay - slack and bx + bw <= ax + aw + slack
            and by + bh <= ay + ah + slack and aw * ah > bw * bh)


_BIN_CENTRES = np.stack(np.meshgrid(np.arange(16), np.arange(16), np.arange(16),
                                    indexing="ij"), -1).reshape(-1, 3) * 16 + 8


def _BIN_LUT_DIST(colour):
    """uint8 lookup (bin -> 1/0): is the bin centre within COLOUR_TOL (+ half a bin)?"""
    return (np.abs(_BIN_CENTRES - colour).max(axis=1) <= COLOUR_TOL + 8).astype(np.uint8)


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    iw = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    ih = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = iw * ih
    return inter / float(aw * ah + bw * bh - inter) if inter else 0.0


MAX_COLOURS = 8     # distinct non-background colours examined for solid boxes
COLOUR_TOL = 24     # max per-channel distance from a box colour (anti-aliasing, gradients)
MAX_REGIONS = 12


def _line_inside(l, box, base):
    lx, ly, lw, lh = (v * base for v in l['rect'])
    x, y, w, h = box
    return lx >= x - 2 and ly >= y - 2 and lx + lw <= x + w + 2 and ly + lh <= y + h + 2


def ocr_solid_regions(img, lines, base):
    """Re-OCR (x2 upscale, crop only) the solid coloured boxes of `img`. `lines` are the
    page-pass lines (coordinates of the original capture; `base` = img px per original px).
    Returns (kept_lines, extra_lines): page-pass lines inside a box are replaced by the box
    pass when that one read more characters (the page pass often finds only a fragment)."""
    boxes = sorted(find_solid_regions(img), key=lambda b: -b[2] * b[3])[:MAX_REGIONS]
    drop, extra = set(), []
    for k, box in enumerate(boxes):
        x, y, w, h = box
        x0, y0 = max(0, x - REGION_PAD), max(0, y - REGION_PAD)
        crop = img[y0:y + h + REGION_PAD, x0:x + w + REGION_PAD]
        crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        data = _tesseract_data(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        if not data:
            continue
        new = _parse_data(data, base * 2, strip=REGION_STRIP_BASE + k)
        for l in new:
            rx, ry, rw, rh = l['rect']
            l['rect'] = (rx + int(x0 / base), ry + int(y0 / base), rw, rh)
        old = [i for i, l in enumerate(lines) if _line_inside(l, box, base)]
        if sum(len(n['text']) for n in new) > sum(len(lines[i]['text']) for i in old):
            drop.update(old)
            extra.extend(new)
    return [l for i, l in enumerate(lines) if i not in drop], extra


ADAPTIVE_BLOCK = 31   # local-threshold window (px), larger than a glyph stroke/letter
ADAPTIVE_C = 12       # a pixel is ink if it is this much darker (or lighter) than its neighbourhood


def _ink_mask(gray):
    """255 where there is text ink, found with a LOCAL threshold so a coloured button or bar
    on a white page is not one big blob (global Otsu splits page vs. button and loses its
    text). Both dark-on-light and light-on-dark ink are computed; the sparser one is text."""
    dark = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV, ADAPTIVE_BLOCK, ADAPTIVE_C)
    light = cv2.adaptiveThreshold(255 - gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                  cv2.THRESH_BINARY_INV, ADAPTIVE_BLOCK, ADAPTIVE_C)
    return light if np.count_nonzero(light) < np.count_nonzero(dark) else dark


def find_strip_cuts(gray, n_strips, min_gap=4):
    """y positions to cut `gray` into up to `n_strips` strips, only inside runs of
    >= min_gap fully blank pixel rows (cut in the middle of the run, so no text line is
    split and each strip keeps a margin). Cuts are the blank runs nearest to an even split;
    fewer (or none) are returned if the image has no suitable gaps."""
    h = gray.shape[0]
    if n_strips < 2:
        return []
    blank = ~(_ink_mask(gray).any(axis=1))
    runs = []   # (centre, length) of blank runs strictly inside the image
    y = 0
    while y < h:
        if blank[y]:
            start = y
            while y < h and blank[y]:
                y += 1
            if start > 0 and y < h and y - start >= min_gap:
                runs.append(((start + y) // 2, y - start))
        else:
            y += 1
    cuts = []
    for k in range(1, n_strips):
        ideal = k * h / n_strips
        near = [r for r in runs if abs(r[0] - ideal) <= h / (2 * n_strips) and r[0] not in cuts]
        if near:
            cuts.append(min(near, key=lambda r: abs(r[0] - ideal))[0])
    return sorted(cuts)


def strip_count(height):
    return max(1, min(os.cpu_count() or 1, height // MIN_STRIP_HEIGHT, MAX_STRIPS))


def ocr_strips(img, scale_factor=1.0):
    """Tesseract on horizontal strips in parallel (one Tesseract engine per thread),
    merged back into whole-image coordinates. Falls back to one pass when the image is
    short or has no clean cut."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cuts = find_strip_cuts(gray, strip_count(gray.shape[0]))
    if not cuts:
        return ocr_tesseract(img, scale_factor)
    bounds = [0] + cuts + [gray.shape[0]]
    spans = list(zip(bounds[:-1], bounds[1:]))
    with ThreadPoolExecutor(max_workers=len(spans)) as pool:
        datas = list(pool.map(lambda sp: _tesseract_data(gray[sp[0]:sp[1]]), spans))
    lines = []
    for i, ((top, _), data) in enumerate(zip(spans, datas)):
        if data:
            lines.extend(_parse_data(data, scale_factor, y_offset=top, strip=i))
    return lines


def tesseract_lang():
    """Tesseract language(s): --ocr-lang if given, else 'eng' for --src en, else 'deu'
    (the deu model also reads English Latin text well, and is faster than eng+deu)."""
    if CONFIG.ocr_lang:
        return CONFIG.ocr_lang
    return 'eng' if CONFIG.source_lang == 'en' else 'deu'


def ocr_tesseract(img, scale_factor=1.0):
    """One Tesseract run over the whole image; rects in original-capture coordinates."""
    data = _tesseract_data(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    return _parse_data(data, scale_factor) if data else []


_TESSDATA_GLOBS = ("/usr/share/tesseract-ocr/*/tessdata", "/usr/share/tessdata",
                   "/usr/local/share/tessdata")
_pools = {}              # (tessdata path, lang, thresholding method) -> queue.Queue of idle PyTessBaseAPI
_pools_lock = threading.Lock()


def tessdata_dirs():
    """Existing candidate directories, best first: $TESSDATA_PREFIX (or its tessdata/
    subdirectory), the app data dir (filled by scripts/setup_models.sh), then the usual
    system locations (skipped when PYTRANSLATE_NO_LEGACY_PATHS is set)."""
    cands = []
    env = os.environ.get("TESSDATA_PREFIX")
    if env:
        cands += [env, os.path.join(env, "tessdata")]
    cands.append(os.path.join(mt.app_data_dir(), "tessdata"))
    if not os.environ.get("PYTRANSLATE_NO_LEGACY_PATHS"):
        for g in _TESSDATA_GLOBS:
            cands += sorted(glob.glob(g), reverse=True)
    return [c for c in cands if os.path.isdir(c)]


def _has_langs(directory, lang):
    return all(os.path.isfile(os.path.join(directory, f"{l}.traineddata")) for l in (lang or "").split("+") if l)


def has_tessdata(lang):
    """True if one directory holds the traineddata for every language in `lang` ('deu', 'eng+deu')."""
    return any(_has_langs(c, lang) for c in tessdata_dirs())


def find_tessdata(lang=None):
    """Directory holding the traineddata files (see tessdata_dirs); prefers one that has
    every language in `lang`, else the first existing directory, else ''."""
    cands = tessdata_dirs()
    for c in cands:
        if _has_langs(c, lang):
            return c
    return cands[0] if cands else ""


def _acquire_api(lang):
    path = find_tessdata(lang)
    method = str(CONFIG.ocr_threshold_method)
    with _pools_lock:
        pool = _pools.setdefault((path, lang, method), queue.Queue())
    try:
        return pool, pool.get_nowait()
    except queue.Empty:
        pass
    try:
        api = tesserocr.PyTessBaseAPI(path=path, lang=lang, oem=tesserocr.OEM.LSTM_ONLY)
        # Global Otsu merges a coloured button/bar on a white page into one blob and loses its
        # text; a local method (Sauvola) keeps it at no measurable speed cost.
        api.SetVariable("thresholding_method", method)
        return pool, api
    except RuntimeError:
        raise OcrError(f"Tesseract language data '{lang}' is missing "
                       f"(run ./scripts/setup_models.sh, or choose another with --ocr-lang).")


def close_apis():
    """Free all pooled Tesseract engines (also runs at interpreter exit)."""
    with _pools_lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        while True:
            try:
                pool.get_nowait().End()
            except queue.Empty:
                break


atexit.register(close_apis)


def _recognize_words(gray):
    """Run Tesseract on a grayscale uint8 image. Returns word tuples
    (text, conf, left, top, width, height, block, par, line) in reading order, with
    block/par/line numbered from 1 like Tesseract's TSV output; [] if nothing found."""
    lang = tesseract_lang()
    pool, api = _acquire_api(lang)
    words = []
    try:
        gray = np.ascontiguousarray(gray)
        h, w = gray.shape[:2]
        api.SetImageBytes(gray.tobytes(), w, h, 1, w)
        try:
            api.Recognize()
            it = api.GetIterator()
        except RuntimeError:
            return []
        if it is None:
            return []
        RIL = tesserocr.RIL
        block = par = line = 0
        while True:
            if it.IsAtBeginningOf(RIL.BLOCK):
                block, par, line = block + 1, 0, 0
            if it.IsAtBeginningOf(RIL.PARA):
                par, line = par + 1, 0
            if it.IsAtBeginningOf(RIL.TEXTLINE):
                line += 1
            try:
                text = it.GetUTF8Text(RIL.WORD)
                conf = it.Confidence(RIL.WORD)
            except RuntimeError:
                text, conf = None, 0.0
            box = it.BoundingBox(RIL.WORD)
            if text and text.strip() and box:
                l, t, r, b = box
                words.append((text, conf, l, t, r - l, b - t, block, par, line))
            if not it.Next(RIL.WORD):
                break
    finally:
        pool.put(api)
    return words


def _tesseract_data(gray):
    """Word tuples for a grayscale image, or None if no text was found."""
    return _recognize_words(gray) or None


def robust_text_h(texts, rects):
    """Text height of a line from its word boxes: median height after dropping outliers
    (single-character/punctuation words and boxes taller than 2x the median)."""
    hs = [r[3] for r in rects]
    if not hs:
        return 0
    med = float(np.median(hs))
    keep = [r[3] for t, r in zip(texts, rects)
            if sum(c.isalnum() for c in t) > 1 and r[3] <= 2 * med]
    if not keep:
        keep = [h for h in hs if h <= 2 * med] or hs
    return float(np.median(keep))


def _parse_data(words, scale_factor, y_offset=0, strip=0):
    """Turn word tuples from _recognize_words into lines.

    `y_offset` (pixels of the OCRed image) shifts a strip back into whole-image
    coordinates; `strip` namespaces block ids (strip*1000 + block) and is kept on
    every line so layout can tell strip boundaries from real paragraph breaks.
    """
    lines = []
    scale_back = 1.0 / scale_factor

    line_dict = {}
    for text, conf, left, top, width, height, block, par, line in words:
        text = text.strip()
        if not text or conf < CONFIG.min_ocr_conf:
            continue
        if len(text) == 1 and not text.isalnum():
            continue   # lone punctuation: button/box edges read as "[" or "|"
        key = (strip * 1000 + block, par, line)

        x = int(left * scale_back)
        y = int((top + y_offset) * scale_back)
        w = int(width * scale_back)
        h = int(height * scale_back)

        if key not in line_dict:
            line_dict[key] = {'text': [], 'rects': [], 'confs': []}

        line_dict[key]['text'].append(text)
        line_dict[key]['rects'].append((x, y, w, h))
        line_dict[key]['confs'].append(conf)

    for key in sorted(line_dict.keys()):
        words = line_dict[key]['text']
        rects = line_dict[key]['rects']
        confs = line_dict[key]['confs']
        # Tesseract can merge side-by-side columns into one "line": split it
        # wherever two neighbouring words are far apart horizontally.
        med_h = float(np.median([r[3] for r in rects]))
        segments = [([words[0]], [rects[0]], [confs[0]])]
        for word, rect, conf in zip(words[1:], rects[1:], confs[1:]):
            prev = segments[-1][1][-1]
            if rect[0] - (prev[0] + prev[2]) > CONFIG.column_gap_factor * med_h:
                segments.append(([], [], []))
            segments[-1][0].append(word)
            segments[-1][1].append(rect)
            segments[-1][2].append(conf)

        for seg_words, seg_rects, seg_confs in segments:
            min_x = min(r[0] for r in seg_rects)
            min_y = min(r[1] for r in seg_rects)
            max_x = max(r[0] + r[2] for r in seg_rects)
            max_y = max(r[1] + r[3] for r in seg_rects)
            lines.append({
                'text': " ".join(seg_words),
                'rect': (min_x, min_y, max_x - min_x, max_y - min_y),
                'text_h': robust_text_h(seg_words, seg_rects),
                'conf': float(np.mean(seg_confs)),
                'block': key[0],
                'par': key[1],
                'strip': strip,
            })

    return lines
