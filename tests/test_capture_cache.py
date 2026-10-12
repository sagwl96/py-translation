import numpy as np

from pytranslate import worker as worker_mod


def _img(v=255):
    img = np.full((80, 120, 3), v, np.uint8)
    img[20:40, 20:100] = 0
    return img


def _run(img, monkeypatch, calls, dpr=1.0):
    w = worker_mod.TranslationWorker(img, dpr=dpr)

    def fake_ocr(i, sf=1.0):
        calls.append(1)
        return [{"text": "x", "rect": (20, 20, 80, 20)}]
    monkeypatch.setattr(w, "_perform_ocr", fake_ocr)
    monkeypatch.setattr(w, "_translate_paragraphs", lambda p, report=None: p)
    got = []
    w.finished_translation.connect(got.append)
    w.run()
    return got[0]


def test_second_identical_capture_skips_ocr(monkeypatch):
    calls = []
    first = _run(_img(), monkeypatch, calls)
    second = _run(_img(), monkeypatch, calls)
    assert len(calls) == 1
    assert second == first and second is not first


def test_changed_capture_or_settings_miss(monkeypatch):
    calls = []
    _run(_img(), monkeypatch, calls)
    _run(_img(200), monkeypatch, calls)                     # different pixels
    from pytranslate.config import CONFIG
    monkeypatch.setattr(CONFIG, "target_lang", "fr")
    _run(_img(200), monkeypatch, calls)                     # different target language
    assert len(calls) == 3


def test_failed_run_not_cached(monkeypatch):
    calls = []
    w = worker_mod.TranslationWorker(_img())
    monkeypatch.setattr(w, "_perform_ocr", lambda i, sf=1.0: (_ for _ in ()).throw(ValueError("x")))
    w.error.connect(lambda m: None)
    w.run()
    _run(_img(), monkeypatch, calls)
    assert len(calls) == 1
