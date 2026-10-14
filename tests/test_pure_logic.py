import numpy as np
import pytest

from pytranslate import layout, ocr
from pytranslate.config import CONFIG


def line(text, x, y, w, h):
    return {"text": text, "rect": (x, y, w, h)}


# _horizontal_overlap

def test_overlap_identical():
    assert layout.horizontal_overlap((10, 100), (10, 100)) == 1.0


def test_overlap_disjoint():
    assert layout.horizontal_overlap((0, 50), (60, 50)) == 0
    assert layout.horizontal_overlap((0, 50), (50, 50)) == 0  # touching


def test_overlap_partial_normalised_by_smaller():
    # overlap 50 px, smaller width 100 -> 0.5
    assert layout.horizontal_overlap((0, 100), (50, 200)) == pytest.approx(0.5)


def test_overlap_contained():
    assert layout.horizontal_overlap((0, 200), (50, 40)) == 1.0


def test_overlap_zero_width():
    assert layout.horizontal_overlap((10, 0), (10, 50)) == 0


# _make_paragraph

def test_make_paragraph():
    lines = [line("Hallo", 10, 20, 100, 15), line("Welt", 30, 40, 150, 15)]
    p = layout.make_paragraph(lines)
    assert p["text"] == "Hallo Welt"
    assert p["par_rect"] == (10, 20, 170, 35)
    assert p["line_rects"] == [(10, 20, 100, 15), (30, 40, 150, 15)]


# _group_lines_to_paragraphs

def test_group_empty():
    assert layout.group_lines_to_paragraphs([]) == []


def test_group_single_column_one_paragraph():
    lines = [line("eins", 10, 10, 200, 20), line("zwei", 10, 35, 200, 20),
             line("drei", 10, 60, 200, 20)]
    pars = layout.group_lines_to_paragraphs(lines)
    assert len(pars) == 1
    assert pars[0]["text"] == "eins zwei drei"


def test_group_unsorted_input_is_sorted():
    lines = [line("zwei", 10, 35, 200, 20), line("eins", 10, 10, 200, 20)]
    pars = layout.group_lines_to_paragraphs(lines)
    assert [p["text"] for p in pars] == ["eins zwei"]


def test_group_large_gap_two_paragraphs():
    lines = [line("oben", 10, 10, 200, 20), line("unten", 10, 200, 200, 20)]
    pars = layout.group_lines_to_paragraphs(lines)
    assert [p["text"] for p in pars] == ["oben", "unten"]


# _preprocess_image

def test_preprocess_no_downscale_when_small():
    img = np.zeros((100, 500, 3), np.uint8)
    out, sf = ocr.preprocess_image(img)
    assert out.shape == (100, 500, 3)
    assert sf == 1.0


def test_preprocess_downscale_sets_scale_factor():
    img = np.zeros((1000, 5120, 3), np.uint8)
    out, sf = ocr.preprocess_image(img)
    assert sf == pytest.approx(0.5)
    assert out.shape == (500, 2560, 3)


def test_preprocess_no_downscale_at_1920():
    img = np.zeros((100, 1920, 3), np.uint8)
    out, sf = ocr.preprocess_image(img)
    assert out.shape == (100, 1920, 3)
    assert sf == 1.0


def test_preprocess_disabled(monkeypatch):
    monkeypatch.setattr(CONFIG, "max_ocr_width", 0)
    img = np.zeros((10, 5000, 3), np.uint8)
    out, sf = ocr.preprocess_image(img)
    assert out is img and sf == 1.0


# ---------------------------------------------------------------------------
# P3.1: Tesseract block/par ids and column-aware grouping
# ---------------------------------------------------------------------------
def _ln(text, x, y, w=200, h=20, block=None, par=None):
    d = {"text": text, "rect": (x, y, w, h)}
    if block is not None:
        d["block"], d["par"] = block, par
    return d


def test_group_columns_read_top_to_bottom_per_column():
    lines = [_ln("L0", 10, 10), _ln("R0", 400, 10), _ln("L1", 10, 35), _ln("R1", 400, 35)]
    pars = layout.group_lines_to_paragraphs(lines)
    assert [p["text"] for p in pars] == ["L0 L1", "R0 R1"]


def test_group_splits_on_tesseract_par_change():
    lines = [_ln("a", 10, 10, block=1, par=1), _ln("b", 10, 32, block=1, par=2)]
    assert len(layout.group_lines_to_paragraphs(lines)) == 2


def test_group_same_par_but_big_gap_is_split():
    lines = [_ln("a", 10, 10, block=1, par=1), _ln("b", 10, 200, block=1, par=1)]
    assert len(layout.group_lines_to_paragraphs(lines)) == 2


def test_group_same_par_close_lines_merge():
    lines = [_ln("a", 10, 10, block=1, par=1), _ln("b", 10, 32, block=1, par=1)]
    assert len(layout.group_lines_to_paragraphs(lines)) == 1


# P8.3: one Tesseract pass; the scale is chosen from the estimated glyph height
def _fake_ocr(monkeypatch):
    """Stub ocr_tesseract: record (width, scale) and return a line in original coordinates."""
    calls = []

    def fake(img, scale_factor=1.0):
        calls.append((img.shape[1], scale_factor))
        sf = scale_factor
        return [{"text": "wort", "rect": (int(10 / sf), int(10 / sf), int(100 / sf), int(20 / sf))}]
    monkeypatch.setattr(ocr, "ocr_tesseract", fake)
    return calls


def _text_img(width, glyph_h):
    """White image with a row of black glyph-like blobs of height glyph_h."""
    img = np.full((100, width, 3), 255, np.uint8)
    for x in range(10, width - 20, glyph_h + 6):
        img[20:20 + glyph_h, x:x + glyph_h - 1] = 0
    return img


def test_small_glyphs_upscaled_single_pass(monkeypatch):
    calls = _fake_ocr(monkeypatch)
    lines = ocr.perform_ocr(_text_img(600, 4))
    assert calls == [(1200, 2.0)]
    assert lines[0]["rect"][:3] == (5, 5, 50)


def test_large_glyphs_single_pass_unscaled(monkeypatch):
    calls = _fake_ocr(monkeypatch)
    ocr.perform_ocr(_text_img(1500, 12))
    assert calls == [(1500, 1.0)]


def test_upscale_composes_with_downscale_factor(monkeypatch):
    calls = _fake_ocr(monkeypatch)
    ocr.perform_ocr(_text_img(900, 3), 0.5)
    assert calls == [(1800, 1.0)]


def test_glyph_height_estimate_light_on_dark():
    img = 255 - _text_img(600, 10)
    assert ocr.estimate_glyph_height(img) == 10
    assert ocr.estimate_glyph_height(np.full((50, 50, 3), 255, np.uint8)) == 0.0


# P8.4: parallel strips
def _rows_img(blocks, h=600, w=400):
    """White image with black ink bars at the given (y0, y1) row ranges."""
    img = np.full((h, w, 3), 255, np.uint8)
    for y0, y1 in blocks:
        img[y0:y1, 20:80] = 0
    return img


def test_cuts_only_in_blank_rows_and_never_through_ink():
    gray = _rows_img([(10, 40), (50, 140), (160, 290), (300, 440), (470, 590)])[:, :, 0]
    cuts = ocr.find_strip_cuts(gray, 4)
    assert cuts and all(not (gray[c] < 128).any() for c in cuts)
    assert cuts == sorted(set(cuts))


def test_no_clean_cut_means_single_pass(monkeypatch):
    img = np.full((600, 400, 3), 255, np.uint8)
    img[:, 100] = 0   # a vertical rule: no row is blank
    assert ocr.find_strip_cuts(img[:, :, 0], 4) == []
    seen = []
    monkeypatch.setattr(ocr, "ocr_tesseract", lambda i, sf=1.0: seen.append(i.shape) or [])
    ocr.ocr_strips(img)
    assert seen == [img.shape]


def test_strip_count_capped():
    assert ocr.strip_count(100) == 1
    assert ocr.strip_count(10000) <= ocr.MAX_STRIPS


def _word_data(text, top):
    return [(text, 95.0, 10, top, 50, 12, 1, 1, 1)]


def test_strips_merge_with_offsets_and_namespaced_blocks(monkeypatch):
    img = _rows_img([(10, 40), (50, 140), (160, 290), (300, 440), (470, 590)])
    monkeypatch.setattr(ocr, "strip_count", lambda h: 2)
    tops = []

    def fake(gray):
        tops.append(gray.shape[0])
        return _word_data("w%d" % len(tops), 5)
    monkeypatch.setattr(ocr, "_recognize_words", fake)
    lines = ocr.ocr_strips(img, 0.5)
    assert len(lines) == 2 and sum(tops) == 600
    lines.sort(key=lambda l: l["rect"][1])
    assert lines[0]["rect"][1] == 10 and lines[1]["rect"][1] == 2 * (5 + tops[0])   # offset, /0.5
    assert {l["block"] // 1000 for l in lines} == {0, 1}
    assert [l["strip"] for l in lines] == [0, 1]


def test_layout_merges_paragraph_across_strip_boundary_but_not_columns():
    def ln(t, x, y, strip, blk):
        return {"text": t, "rect": (x, y, 200, 20), "block": strip * 1000 + blk, "par": 1, "strip": strip}
    lines = [ln("a", 10, 10, 0, 1), ln("b", 10, 34, 1, 1),            # same column, adjacent strips
             ln("c", 400, 10, 0, 2), ln("d", 400, 34, 1, 2)]           # second column
    pars = layout.group_lines_to_paragraphs(lines)
    assert sorted(p["text"] for p in pars) == ["a b", "c d"]
