"""Tests for Phase 2 correctness fixes."""
import numpy as np
from PyQt6 import QtGui

from pytranslate import translate, ocr, ui, worker as worker_mod
from pytranslate.capture import qimage_to_bgr, scale_rects
from pytranslate.config import CONFIG


def test_qimage_to_bgr_red_rgb32(qapp):
    img = QtGui.QImage(5, 3, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor(255, 0, 0))
    bgr = qimage_to_bgr(img)
    assert bgr.shape == (3, 5, 3)
    assert (bgr == np.array([0, 0, 255], np.uint8)).all()


def test_qimage_to_bgr_honours_stride(qapp):
    # width 3 -> RGB888 rows are padded to 4-byte boundary (9 -> 12 bytes)
    img = QtGui.QImage(3, 2, QtGui.QImage.Format.Format_RGB888)
    img.fill(QtGui.QColor(0, 255, 0))
    assert img.bytesPerLine() != 3 * 3
    bgr = qimage_to_bgr(img)
    assert bgr.shape == (2, 3, 3)
    assert (bgr == np.array([0, 255, 0], np.uint8)).all()


def test_pyflakes_no_unused_imports():
    import subprocess, sys, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "-m", "pyflakes", os.path.join(root, "pytranslate")],
                       capture_output=True, text=True)
    assert "imported but unused" not in r.stdout, r.stdout


def test_main_window_constructs(qapp):
    w = ui.MainWindow()
    assert w.overlay_labels == []
    w.close()


def test_missing_model_is_looked_up_once_and_reported(monkeypatch):
    import pytest
    calls = []
    monkeypatch.setattr(translate, "_ARGOS_CACHE", {})
    monkeypatch.setattr(translate, "_find_installed_argos", lambda s, t: calls.append(1))
    for text in ("a", "b"):
        with pytest.raises(translate.ModelMissingError, match="setup_models.sh"):
            translate.translate_argos(text, "de")
    assert len(calls) == 1


def test_default_mode_never_calls_google_even_when_argos_fails(monkeypatch):
    """Strict offline: an Argos failure keeps the original text and reports the error."""
    import sys

    class Loud:
        def __init__(self, *a, **k):
            raise AssertionError("Google must not be used in offline mode")

    monkeypatch.setattr(translate, "GoogleTranslator", Loud)
    monkeypatch.setitem(sys.modules, "deep_translator", None)   # any import would fail loudly
    monkeypatch.setattr(translate, "translate_google",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    monkeypatch.setattr(CONFIG, "offline", True)
    monkeypatch.setattr(CONFIG, "source_lang", "de")

    class Broken:
        def translate(self, text, beam=2):
            raise RuntimeError("model exploded")

    monkeypatch.setattr(translate, "_ARGOS_CACHE", {("de", "en"): Broken()})
    report = translate.TranslationReport()
    pars = [{"text": "Guten Morgen"}, {"text": "Gute Nacht"}]
    out = translate.translate_paragraphs(pars, report=report)
    assert [p["text"] for p in out] == ["Guten Morgen", "Gute Nacht"]
    assert report.all_failed and "model exploded" in report.errors[0]

    monkeypatch.setattr(translate, "_ARGOS_CACHE", {("de", "en"): None})   # model not installed
    report = translate.TranslationReport()
    out = translate.translate_paragraphs([{"text": "Guten Tag"}], report=report)
    assert out[0]["text"] == "Guten Tag"
    assert "setup_models.sh" in report.errors[0]


def test_online_without_extra_gives_clear_startup_error(monkeypatch, capsys):
    import sys
    from pytranslate.__main__ import main
    monkeypatch.setattr(translate, "GoogleTranslator", None)
    monkeypatch.setitem(sys.modules, "deep_translator", None)
    from dataclasses import fields
    for f in fields(CONFIG):
        monkeypatch.setattr(CONFIG, f.name, getattr(CONFIG, f.name))   # restored on teardown
    assert main(["pytranslate", "--online"]) == 2
    assert "uv sync --extra online" in capsys.readouterr().err


def test_low_confidence_word_dropped(monkeypatch):
    from .helpers import words_from_fixture
    # a junk word appended to the first line (block 1, par 1, line 1) with low conf
    words = words_from_fixture([("xq#", 12.0, 210, 22, 20, 20, 1, 1, 1)])
    monkeypatch.setattr(ocr, "_recognize_words", lambda gray: words)
    lines = ocr.ocr_tesseract(np.full((300, 400, 3), 255, np.uint8))
    assert [l["text"] for l in lines] == ["Guten Morgen", "wie geht's"]


def test_scale_rects():
    assert scale_rects([(200, 100, 400, 60)], 2.0) == [(100, 50, 200, 30)]
    assert scale_rects([(10, 20, 30, 40)], 1.0) == [(10, 20, 30, 40)]
    assert scale_rects([(10, 20, 30, 40)], 1.5) == [(7, 13, 20, 27)]


def test_capture_geometry_offscreen(qapp):
    w = ui.MainWindow()
    w.show()
    screen, x, y, cw, ch = w.get_capture_geometry()
    assert screen is w.screen()
    assert cw > 0 and ch > 0
    gx, gy, _, _ = w.get_transparent_area_geometry()
    assert (x, y) == (gx - screen.geometry().x(), gy - screen.geometry().y())
    w.close()


def test_worker_divides_rects_by_dpr(monkeypatch):
    w = worker_mod.TranslationWorker(np.full((50, 50, 3), 255, np.uint8), dpr=2.0)
    monkeypatch.setattr(w, "_perform_ocr", lambda img, sf=1.0: [{"text": "x", "rect": (20, 40, 100, 20)}])
    monkeypatch.setattr(w, "_translate_paragraphs", lambda p, report=None: p)
    got = []
    w.finished_translation.connect(got.append)
    w.run()
    assert got[0][0]["par_rect"] == (10, 20, 50, 10)
    assert got[0][0]["line_rects"] == [(10, 20, 50, 10)]


class _FakeScreen:
    def __init__(self, seen):
        self.seen = seen

    def devicePixelRatio(self):
        return 1.0

    def grabWindow(self, wid, x, y, w, h):
        win = self.seen["win"]
        self.seen["overlays"] = len(win.overlay_labels)
        self.seen["status_visible"] = win.central.status_label.isVisible()
        self.seen["hint"] = win.central.hint.isVisible()
        self.seen["popover"] = win.central.shortcuts.isVisible()
        self.seen["flash"] = win.central.flash_active()
        self.seen["busy"] = win.busy
        self.seen["args"] = (wid, x, y, w, h)
        pm = QtGui.QPixmap(w, h)
        pm.fill(QtGui.QColor(255, 255, 255))
        return pm


def test_capture_hides_ui_before_grab(qapp, monkeypatch):
    from PyQt6 import QtCore, QtWidgets
    seen = {}
    win = ui.MainWindow()
    seen["win"] = win
    win.show()
    # pre-existing overlay + visible toast
    label = QtWidgets.QLabel("old", win.capture_area)
    label.show()
    win.overlay_labels.append(label)
    win.central.show_status("Old toast", 5000)
    assert win.central.status_label.isVisible()

    monkeypatch.setattr(win, "get_capture_geometry", lambda: (_FakeScreen(seen), 1, 2, 30, 20))
    # do not actually run OCR
    monkeypatch.setattr(worker_mod.TranslationWorker, "start", lambda self: None)

    win.capture_transparent_area()
    assert win.overlay_labels == []           # cleared during prepare
    assert not win.central.status_label.isVisible()
    assert "args" not in seen                 # grab is deferred
    deadline = QtCore.QDeadlineTimer(2000)
    while "args" not in seen and not deadline.hasExpired():
        qapp.processEvents()
    assert seen["args"] == (0, 1, 2, 30, 20)
    assert seen["overlays"] == 0
    assert seen["status_visible"] is False
    assert seen["hint"] is False and seen["popover"] is False and seen["flash"] is False
    assert seen["busy"] is True   # the toolbar spinner is on, but it lives outside the capture rect
    win.worker = None
    win.close()


def test_close_does_not_block_on_slow_translator(qapp, monkeypatch):
    import time
    win = ui.MainWindow()
    win.show()
    monkeypatch.setattr(worker_mod.TranslationWorker, "_preprocess_image", lambda self, img: (img, 1.0))
    monkeypatch.setattr(worker_mod.TranslationWorker, "_perform_ocr", lambda self, img, sf=1.0: [
        {"text": f"line {i}", "rect": (0, i * 200, 100, 20)} for i in range(40)])
    monkeypatch.setattr(translate, "translate_text",
                        lambda text, src='de': time.sleep(0.3) or text)
    started = []
    worker = worker_mod.TranslationWorker(np.full((10, 10, 3), 255, np.uint8))
    worker.started.connect(lambda: started.append(1))
    win.worker = worker
    worker.start()
    deadline = time.monotonic() + 2
    while not started and time.monotonic() < deadline:
        qapp.processEvents()
    time.sleep(0.1)
    t0 = time.monotonic()
    win.close()
    elapsed = time.monotonic() - t0
    assert elapsed < 3, elapsed
    assert not worker.isRunning()   # 40 x 0.3 s would have taken 12 s


def test_detect_lang():
    assert translate.detect_lang("Guten Morgen, wie geht es dir?") == 'de'
    assert translate.detect_lang("Hello, how are you?") == 'en'
    assert translate.detect_lang("Schöne Grüße") == 'de'
    assert translate.detect_lang("Die Katze ist nicht auf dem Tisch.") == 'de'
    assert translate.detect_lang("The cat is on the table and it is not happy.") == 'en'
    assert translate.detect_lang("Straße") == 'de'


def _pars(text):
    return [{"text": text, "par_rect": (0, 0, 1, 1), "line_rects": [(0, 0, 1, 1)]}]


def test_german_paragraph_translated_real_argos(monkeypatch):
    monkeypatch.setattr(CONFIG, "source_lang", "auto")
    out = translate.translate_paragraphs(_pars("Guten Morgen, wie geht es dir?"))
    assert out[0]["text"] != "Guten Morgen, wie geht es dir?"
    assert "morning" in out[0]["text"].lower()


def test_english_paragraph_unchanged(monkeypatch):
    monkeypatch.setattr(CONFIG, "source_lang", "auto")
    monkeypatch.setattr(translate, "translate_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    out = translate.translate_paragraphs(_pars("Hello, how are you?"))
    assert out[0]["text"] == "Hello, how are you?"


def test_src_lang_passed_to_google(monkeypatch):
    seen = {}

    class FakeGT:
        def __init__(self, source, target):
            seen["src"], seen["tgt"] = source, target

        def translate(self, text):
            return "G:" + text

    monkeypatch.setattr(translate, "GoogleTranslator", FakeGT)
    monkeypatch.setattr(CONFIG, "offline", False)
    monkeypatch.setattr(CONFIG, "source_lang", "auto")
    out = translate.translate_paragraphs(_pars("Guten Morgen, wie geht es dir?"))
    assert out[0]["text"].startswith("G:")
    assert seen == {"src": "de", "tgt": "en"}


def test_detect_lang_tie_defaults_to_german():
    assert translate.detect_lang("Ausgang") == 'de'
    assert translate.detect_lang("Bahnhof Notausgang") == 'de'


def test_worker_reports_partial_translation_failure(monkeypatch):
    worker_mod.clear_capture_cache()
    w = worker_mod.TranslationWorker(np.full((50, 50, 3), 255, np.uint8))
    monkeypatch.setattr(CONFIG, "source_lang", "de")
    monkeypatch.setattr(w, "_perform_ocr", lambda img, sf=1.0: [
        {"text": "eins", "rect": (0, 0, 40, 10)}, {"text": "zwei", "rect": (100, 0, 40, 10)}])
    monkeypatch.setattr(translate, "translate_text",
                        lambda text, src='de': (_ for _ in ()).throw(TimeoutError("timeout")) if text == "zwei" else "one")
    errors = []
    w.error.connect(errors.append)
    w.run()
    assert errors == ["1 of 2 paragraphs not translated: timeout"]
