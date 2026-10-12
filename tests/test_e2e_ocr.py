"""End-to-end: render German text with Qt, run real Tesseract (eng+deu)."""
import pytest

from pytranslate import layout, ocr
from tests.helpers import render_text_image

pytestmark = pytest.mark.usefixtures("qapp")


def test_render_is_bgr_and_colored(qapp):
    img = render_text_image(["x"], size=(60, 40), color=(255, 0, 0), bg=(0, 0, 255))
    assert img.shape == (40, 60, 3)
    assert tuple(img[0, 0]) == (255, 0, 0)  # bg RGB(0,0,255) -> BGR(255,0,0)


def test_single_column_german_recognised():
    lines = ["Guten Morgen, wie geht es Ihnen?",
             "Das Wetter ist heute sehr schön."]
    img = render_text_image(lines, size=(900, 200))
    found = ocr.ocr_tesseract(img)
    text = " ".join(l["text"] for l in found).lower()
    for word in ("guten", "morgen", "wetter", "heute"):
        assert word in text, text
    pars = layout.group_lines_to_paragraphs(found)
    assert len(pars) == 1


def test_inverted_colors_recognised():
    img = render_text_image(["Guten Morgen Welt"], size=(700, 120),
                            color=(255, 255, 255), bg=(20, 20, 20))
    found = ocr.ocr_tesseract(img)
    assert "morgen" in " ".join(l["text"] for l in found).lower()


def test_two_columns_not_interleaved():
    left = ["Der Hund läuft schnell", "durch den grünen Wald", "und bellt laut"]
    right = ["Die Katze schläft ruhig", "auf dem weichen Sofa", "und träumt süß"]
    img = render_text_image(left + right, size=(1000, 220), columns=2)
    pars = layout.group_lines_to_paragraphs(ocr.ocr_tesseract(img))
    texts = [p["text"].lower() for p in pars]
    assert len(pars) == 2, texts
    assert "hund" in texts[0] and "wald" in texts[0] and "bellt" in texts[0]
    assert "katze" in texts[1] and "sofa" in texts[1]


def test_tiny_font_german_recognised():
    lines = ["Guten Morgen, wie geht es Ihnen heute?",
             "Das Wetter ist heute sehr schön und warm.",
             "Wir gehen später in den Park spazieren."]
    img = render_text_image(lines, size=(420, 110), font_px=7, margin=8, line_spacing=1.4)
    small, sf = ocr.preprocess_image(img)
    found_lines = ocr.perform_ocr(small, sf)
    text = " ".join(l["text"] for l in found_lines).lower()
    found = [w for w in ("guten", "morgen", "wetter", "heute", "schön", "später", "park", "spazieren")
             if w in text]
    assert len(found) >= 6  # 1x Tesseract finds none of these at 7 px, (found, text)
    assert sf == 1.0


def test_strips_match_single_pass_and_keep_column_order(monkeypatch):
    left = ["Der Hund läuft schnell", "durch den grünen Wald", "und bellt laut",
            "Er springt über den Bach", "und jagt einen Hasen", "bis zum Abend"]
    right = ["Die Katze schläft ruhig", "auf dem weichen Sofa", "und träumt süß",
             "Sie wacht erst spät auf", "und trinkt etwas Milch", "danach geht sie hinaus"]
    img = render_text_image(left + right, size=(1000, 280), columns=2, font_px=22, line_spacing=1.5)
    monkeypatch.setattr(ocr, "strip_count", lambda h: 1)
    single = ocr.ocr_strips(img)
    monkeypatch.setattr(ocr, "strip_count", lambda h: 3)
    cuts = ocr.find_strip_cuts(img[:, :, 0], 3)
    assert len(cuts) >= 1   # the fixture really exercises the strip path
    strips = ocr.ocr_strips(img)
    words = lambda ls: sorted(w for l in ls for w in l["text"].lower().split())
    assert words(strips) == words(single)
    pars = layout.group_lines_to_paragraphs(strips)
    texts = [p["text"].lower() for p in pars]
    assert len(pars) == 2, texts
    assert "hund" in texts[0] and "abend" in texts[0] and "katze" in texts[1] and "hinaus" in texts[1]
