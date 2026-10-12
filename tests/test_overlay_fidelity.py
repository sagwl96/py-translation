"""Phase 10: overlay layout fidelity on the synthetic library web page."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from tests import helpers  # noqa: E402


@pytest.fixture(scope="module")
def page_run(qapp):
    import render_overlays
    return render_overlays.run()


def test_fixture_renders_with_ground_truth(qapp):
    bgr, regions = helpers.render_web_page()
    assert bgr.shape == (helpers.PAGE_SIZE[1], helpers.PAGE_SIZE[0], 3)
    assert len(regions) == 20
    assert {r["kind"] for r in regions} >= {"title", "meta", "body", "card_header", "link"}


def test_pipeline_produces_overlays_on_fixture(page_run):
    win, bgr, regions, result, metrics = page_run
    assert len(win.overlay_labels) == len(result) >= 10
    assert metrics["n_regions"] == 20


def _w(text, x, y, w, h, line=1):
    return (text, 90.0, x, y, w, h, 1, 1, line)


def test_text_h_ignores_tall_noise_box():
    from pytranslate import ocr
    words = [_w("Hello", 0, 10, 50, 14), _w("big", 60, 10, 30, 15), _w("world", 100, 10, 50, 14),
             _w("ll", 160, 0, 3, 60), _w("again", 170, 10, 50, 13)]
    (line,) = ocr._parse_data(words, 1.0)
    assert line['rect'][3] == 60           # the union rect is inflated by the noise box
    assert line['text_h'] == 14            # the robust estimate is not


def test_paragraph_text_h_is_median_of_lines():
    from pytranslate.layout import make_paragraph
    lines = [{'text': t, 'rect': (0, i * 20, 100, 40), 'text_h': h}
             for i, (t, h) in enumerate([('a', 10), ('b', 12), ('c', 11)])]
    assert make_paragraph(lines)['text_h'] == 11
    assert make_paragraph([{'text': 'x', 'rect': (0, 0, 5, 9)}])['text_h'] == 9


def test_heading_and_small_line_are_separate_paragraphs():
    from pytranslate.layout import group_lines_to_paragraphs
    lines = [{'text': 'Title', 'rect': (20, 40, 280, 34), 'text_h': 28, 'block': 1, 'par': 1},
             {'text': 'meta small', 'rect': (20, 80, 300, 14), 'text_h': 11, 'block': 1, 'par': 1}]
    assert [p['text'] for p in group_lines_to_paragraphs(lines)] == ['Title', 'meta small']
    same = [dict(lines[0], text_h=11, rect=(20, 40, 280, 14)), dict(lines[1], rect=(20, 56, 300, 14))]
    assert len(group_lines_to_paragraphs(same)) == 1


def test_fixture_title_and_meta_are_separate(page_run):
    win, bgr, regions, result, metrics = page_run
    by = {r['text'][:5]: r for r in metrics['regions']}
    assert by['Willk']['n_pars'] == 1 and by['Willk']['merged_with_others'] == 0
    assert by['Zulet']['n_pars'] == 1 and by['Zulet']['merged_with_others'] == 0


def test_fit_font_px_shrinks_until_text_fits(qapp):
    from pytranslate import render
    text = "Please report problems with permissions using the problem report form"
    big = render.fit_font_px(text, 400, 200, 30)
    small = render.fit_font_px(text, 400, 20, 30)
    assert big == 30                       # plenty of room: keeps the start size
    assert render.MIN_PX <= small < big
    assert render.fits(text, 400, 20, small) or small == render.MIN_PX
    assert render.fit_font_px(text, 40, 10, 30) == render.MIN_PX   # hopeless: floor


def test_fit_font_px_never_below_start_when_fits(qapp):
    from pytranslate import render
    assert render.fit_font_px("Hi", 200, 40, 12) == 12
    assert render.fit_font_px("Hi", 200, 40, 3) == render.MIN_PX


def test_elide_to_fit_adds_ellipsis(qapp):
    from pytranslate import render
    text = "one two three four five six seven eight nine ten eleven twelve"
    assert render.elide_to_fit("short", 200, 30, 12) == "short"
    cut = render.elide_to_fit(text, 120, 20, 12)
    assert cut.endswith("…") and render.fits(cut, 120, 20, 12)


def test_labels_cover_source_rect_within_margin(page_run):
    win, bgr, regions, result, metrics = page_run
    for item, label in zip(result, win.overlay_labels):
        x, y, w, h = item['par_rect']
        lx, ly, lw, lh = label.x(), label.y(), label.width(), label.height()
        # grown by the margin, then possibly shrunk by overlap resolution (never grown further)
        assert lx >= x - 3 and ly >= y - 3 and lx + lw <= x + w + 3 and ly + lh <= y + h + 3
        assert label.font_px >= 8


def test_font_size_tracks_source_on_fixture(page_run):
    win, bgr, regions, result, metrics = page_run
    ratios = [r['ratio'] for r in metrics['regions'] if 'ratio' in r]
    assert ratios
    assert all(0.6 <= r <= 1.4 for r in ratios), ratios
    matched = [r for r in metrics['regions'] if 'ratio' in r]
    assert all(r['within_rect'] for r in matched)
    # labels cover their source rect except where overlap resolution trimmed a neighbour
    assert sum(r['covers_rect'] for r in matched) >= 0.7 * len(matched)


def test_sample_background_median_ring():
    import numpy as np
    from pytranslate.capture import sample_background
    img = np.zeros((60, 100, 3), np.uint8)
    img[:] = (50, 100, 200)                  # BGR
    img[20:30, 30:60] = (0, 0, 0)            # "text" inside the rect must be ignored
    assert sample_background(img, (30, 20, 30, 10)) == (200, 100, 50)
    assert sample_background(img, (500, 500, 5, 5)) is None


def test_pick_text_color_contrast(qapp):
    from pytranslate import render
    for bg in [(255, 255, 255), (127, 127, 181), (163, 212, 123), (232, 205, 122), (20, 30, 60), (0, 0, 0)]:
        fg = render.pick_text_color(bg)
        assert render.contrast_ratio(bg, fg) >= 4.5, bg
    assert render.pick_text_color((10, 10, 10)) == render.LIGHT_TEXT
    assert render.pick_text_color((250, 250, 250)) == render.DARK_TEXT


def test_labels_take_background_colour_with_readable_text(page_run):
    import re
    from pytranslate import render
    win, bgr, regions, result, metrics = page_run
    assert all(it['bg'] is not None for it in result)
    colored = [r for r in metrics['regions'] if r.get('bg_err') is not None]
    assert all(r['bg_err'] <= 12 for r in colored), colored
    assert any(r['bg_err'] is not None for r in metrics['regions'])
    for it, label in zip(result, win.overlay_labels):
        m = re.search(r"background-color: rgba\((\d+), (\d+), (\d+)", label.styleSheet())
        assert tuple(map(int, m.groups())) == tuple(it['bg'])
        fg = re.search(r"[^-]color: rgb\((\d+), (\d+), (\d+)", label.styleSheet())
        assert render.contrast_ratio(it['bg'], tuple(map(int, fg.groups()))) >= 4.5


def test_header_bar_labels_use_bar_colour(page_run):
    win, bgr, regions, result, metrics = page_run
    bars = [r for r in metrics['regions'] if r['text'] in ('Veranstaltungen und Kurse', 'Kontakt und Hilfe')]   # the yellow bars
    assert bars and all(r['bg_err'] <= 12 for r in bars if 'bg_err' in r)


def _any_overlap(rects):
    return [(i, j) for i in range(len(rects)) for j in range(i + 1, len(rects))
            if rects[i][2] > 0 and rects[j][2] > 0 and
            min(rects[i][0] + rects[i][2], rects[j][0] + rects[j][2]) > max(rects[i][0], rects[j][0]) and
            min(rects[i][1] + rects[i][3], rects[j][1] + rects[j][3]) > max(rects[i][1], rects[j][1])]


def test_resolve_overlaps_unit():
    from pytranslate.render import resolve_overlaps
    rects = [(0, 0, 100, 30), (10, 25, 100, 30), (200, 0, 50, 20), (240, 5, 40, 20)]
    out = resolve_overlaps(rects)
    assert not _any_overlap(out)
    assert out[0] == rects[0] and out[2] == rects[2]       # earlier rects are untouched
    assert out[1][1] == 30 and out[1][3] == 25             # later one shrank away from the overlap
    assert out[3][0] == 250 and out[3][2] == 30
    thin = resolve_overlaps([(0, 0, 100, 30), (0, 28, 100, 10)])   # shrinking b alone would leave 8... shared
    assert not _any_overlap(thin) and all(r[3] >= 1 for r in thin)
    inner = resolve_overlaps([(0, 0, 100, 100), (10, 10, 20, 20)])
    assert not _any_overlap(inner) and inner[1][2] == 0
    assert resolve_overlaps([(0, 0, 10, 10), (20, 0, 10, 10)]) == [(0, 0, 10, 10), (20, 0, 10, 10)]


def test_no_overlapping_labels_on_fixture(page_run):
    win, bgr, regions, result, metrics = page_run
    assert metrics['overlap_pairs'] == 0
    rects = [(lb.x(), lb.y(), lb.width(), lb.height()) for lb in win.overlay_labels]
    assert not _any_overlap(rects)


def test_overlapping_source_rects_get_separated_labels(qapp):
    from pytranslate.ui import MainWindow
    win = MainWindow()
    win.resize(400, 300)
    res = [{"text": "alpha", "par_rect": (10, 10, 200, 40), "line_rects": [(10, 10, 200, 20)], "text_h": 15},
           {"text": "beta", "par_rect": (10, 40, 200, 40), "line_rects": [(10, 40, 200, 20)], "text_h": 15}]
    win.on_translation_finished(res)
    a, b = win.overlay_labels
    assert a.geometry().bottom() < b.geometry().top()
