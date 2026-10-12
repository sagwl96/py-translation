import numpy as np
import pytest

from pytranslate import ocr
from .helpers import words_from_fixture

@pytest.fixture
def fake_tesseract(monkeypatch):
    words = words_from_fixture()
    calls = []

    def fake(gray):
        calls.append(ocr.tesseract_lang())
        return words

    monkeypatch.setattr(ocr, "_recognize_words", fake)
    return calls


IMG = np.full((300, 400, 3), 255, np.uint8)


def test_two_lines_parsed(fake_tesseract):
    lines = ocr.ocr_tesseract(IMG)
    assert [l["text"] for l in lines] == ["Guten Morgen", "wie geht's"]
    assert lines[0]["rect"] == (10, 20, 200, 30)
    assert lines[1]["rect"] == (10, 70, 300, 30)
    assert fake_tesseract[0] == "deu"


def test_scale_back_applied(fake_tesseract):
    lines = ocr.ocr_tesseract(IMG, 0.5)
    assert lines[0]["rect"] == (20, 40, 400, 60)


def test_no_text_returns_empty(monkeypatch):
    monkeypatch.setattr(ocr, "_recognize_words", lambda gray: [])
    assert ocr.ocr_tesseract(IMG) == []


def test_ocr_lang_override_and_src_default(fake_tesseract, monkeypatch):
    from pytranslate.config import CONFIG
    monkeypatch.setattr(CONFIG, "ocr_lang", "eng+deu")
    ocr.ocr_tesseract(IMG)
    monkeypatch.setattr(CONFIG, "ocr_lang", "")
    monkeypatch.setattr(CONFIG, "source_lang", "en")
    ocr.ocr_tesseract(IMG)
    assert fake_tesseract[-2:] == ["eng+deu", "eng"]


def test_missing_traineddata_is_clear_error(monkeypatch):
    from pytranslate.config import CONFIG
    monkeypatch.setattr(CONFIG, "ocr_lang", "xyz")
    with pytest.raises(ocr.OcrError, match="language data 'xyz'"):
        ocr.ocr_tesseract(IMG)


def test_find_tessdata_prefers_env(tmp_path, monkeypatch):
    (tmp_path / "deu.traineddata").write_bytes(b"")
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path))
    assert ocr.find_tessdata("deu") == str(tmp_path)


def test_real_engine_reuses_pooled_api():
    gray = np.full((60, 200), 255, np.uint8)
    ocr._recognize_words(gray)
    pool = ocr._pools[(ocr.find_tessdata('deu'), 'deu', str(ocr.CONFIG.ocr_threshold_method))]
    n = pool.qsize()
    assert n >= 1
    ocr._recognize_words(gray)
    assert pool.qsize() == n   # engine returned to the pool, none created


def test_omp_not_throttled_process_wide():
    import os
    assert "OMP_THREAD_LIMIT" not in os.environ   # must not throttle Argos/ctranslate2
