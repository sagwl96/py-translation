"""O8: text on coloured buttons/header bars must survive OCR (global Otsu used to lose it)."""
import cv2
import numpy as np
import pytest

from pytranslate import ocr
from tests import helpers

COLORS = ["orange", "blue", "dark blue", "yellow"]


def _texts(img):
    im, sc = ocr.preprocess_image(img)
    return [l["text"] for l in ocr.perform_ocr(im, sc)]


@pytest.mark.parametrize("color", COLORS)
@pytest.mark.parametrize("px", [13, 15])
def test_button_text_recognised_alone(qapp, color, px):
    texts = _texts(helpers.render_button(color, px))
    assert any(t.startswith("Jetzt Mitglied werden") for t in texts), texts
    assert not any(t.strip() in ("[", "|", "]") for t in texts)


@pytest.mark.parametrize("color", ["orange", "blue", "dark blue", "yellow"])
def test_button_text_recognised_on_web_page(qapp, color):
    bgr, regions = helpers.render_web_page(button=color)
    result = helpers.run_page_pipeline(bgr)
    btn = next(r for r in regions if r["kind"] == "button")
    bx, by, bw, bh = btn["rect"]
    inside = [it for it in result if it["par_rect"][0] >= bx - 4 and it["par_rect"][1] >= by - 4
              and it["par_rect"][0] + it["par_rect"][2] <= bx + bw + 4
              and it["par_rect"][1] + it["par_rect"][3] <= by + bh + 4]
    assert inside and inside[0]["text"].startswith("Become a member now"), [i["text"] for i in result]


def test_coloured_header_bars_recognised(qapp):
    bgr, regions = helpers.render_web_page()
    texts = _texts(bgr)
    assert any("Ausleihe" in t for t in texts), texts
    assert any(t.startswith("Öffnungszeiten und Anfahrt") for t in texts)


def test_glyph_height_sees_text_on_coloured_button(qapp):
    est = ocr.estimate_glyph_height(helpers.render_button("blue", 13))
    assert 6 <= est <= 14
    assert ocr.estimate_glyph_height(np.full((60, 60, 3), 255, np.uint8)) == 0.0


def test_strip_cuts_ignore_flat_bar_but_not_text(qapp):
    # a coloured bar with text, then blank page, then dark text: cuts only in blank rows
    img = np.full((600, 400, 3), 255, np.uint8)
    cv2.rectangle(img, (10, 10), (390, 60), (80, 120, 230), -1)
    for y in (20, 40, 200, 220, 400, 420):
        cv2.putText(img, "Wort", (30, y + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cuts = ocr.find_strip_cuts(gray, 4)
    assert cuts
    text_rows = np.where(ocr._ink_mask(gray).any(axis=1))[0]
    assert not set(cuts) & set(text_rows)
    assert not any(cv2.threshold(gray[c:c + 1], 100, 255, cv2.THRESH_BINARY_INV)[1].any() for c in cuts)


def test_find_solid_regions(qapp):
    boxes = ocr.find_solid_regions(helpers.render_button("orange", 14))
    assert len(boxes) == 1 and abs(boxes[0][2] - 205) <= 3 and abs(boxes[0][3] - 30) <= 3
    assert ocr.find_solid_regions(np.full((100, 100, 3), 255, np.uint8)) == []


def test_threshold_method_set_on_engines(qapp):
    ocr.close_apis()
    pool, api = ocr._acquire_api("deu")
    try:
        assert api.GetVariableAsString("thresholding_method") == "2"
    finally:
        pool.put(api)


# --- O9: fallback pass -------------------------------------------------------------------

def test_low_contrast_text_found_by_fallback(qapp):
    img = helpers.render_text_image(["Hallo Welt, das ist ein Test", "Zweite Zeile mit Text"],
                                    size=(500, 120), color=(200, 200, 200), font_px=14)
    im, sc = ocr.preprocess_image(img)
    assert ocr._page_pass(im, sc) == [] or ocr._poor(ocr._page_pass(im, sc))   # first pass fails
    lines = ocr.perform_ocr(im, sc)
    assert any("Welt" in l["text"] for l in lines)
    assert ocr.mean_conf(lines) >= ocr.FALLBACK_MIN_CONF


def test_fallback_not_run_on_normal_text(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(ocr, "_fallback_pass", lambda *a: calls.append(1) or [])
    img = helpers.render_text_image(["Hallo Welt, das ist ein Test", "Zweite Zeile mit Text"],
                                    size=(500, 120), font_px=18)
    lines = ocr.perform_ocr(img, 1.0)
    assert lines and not calls


def test_fallback_keeps_best_scoring_result(qapp, monkeypatch):
    good = [{"text": "abcdef", "conf": 90.0, "rect": (0, 0, 1, 1)}]
    shaky = [{"text": "ab", "conf": 30.0, "rect": (0, 0, 1, 1)}]
    outs = iter([good])
    monkeypatch.setattr(ocr, "_page_pass", lambda img, base: next(outs))
    img = np.full((40, 40, 3), 255, np.uint8)
    assert ocr._fallback_pass(img, 1.0, shaky) == good
    assert ocr.score(good) == 540 and ocr.mean_conf(shaky) == 30
    assert ocr.mean_conf([]) == 0.0
