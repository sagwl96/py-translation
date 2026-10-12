import time

import numpy as np
from PyQt6 import QtGui

from pytranslate import ocr, translate, ui, worker as worker_mod
from pytranslate.config import CONFIG

BLANK = np.full((20, 20, 3), 255, np.uint8)


def _run(w):
    errors, results = [], []
    w.error.connect(errors.append)
    w.finished_translation.connect(results.append)
    w.run()
    return errors, results


def test_tesseract_missing_emits_error(monkeypatch):
    monkeypatch.setattr(CONFIG, "ocr_lang", "xyz")
    errors, results = _run(worker_mod.TranslationWorker(BLANK))
    assert len(errors) == 1 and "Tesseract" in errors[0]
    assert results == [[]]


def test_unexpected_exception_emits_error(monkeypatch):
    monkeypatch.setattr(ocr, "perform_ocr", lambda img, sf=1.0: (_ for _ in ()).throw(ValueError("kaputt")))
    errors, results = _run(worker_mod.TranslationWorker(BLANK))
    assert errors == ["kaputt"]
    assert results == [[]]


def test_all_backends_failed_emits_error(monkeypatch):
    class Boom:
        def __init__(self, **k):
            pass

        def translate(self, text):
            raise RuntimeError("no network")

    monkeypatch.setattr(translate, "GoogleTranslator", Boom)
    monkeypatch.setattr(CONFIG, "offline", False)
    monkeypatch.setattr(CONFIG, "source_lang", "de")
    monkeypatch.setattr(ocr, "perform_ocr", lambda img, sf=1.0: [
        {"text": "Guten Morgen", "rect": (0, 0, 100, 20)}])
    errors, results = _run(worker_mod.TranslationWorker(BLANK))
    assert len(errors) == 1 and "no network" in errors[0]
    assert results[0][0]["text"] == "Guten Morgen"   # original text kept


def test_no_error_on_success(monkeypatch):
    monkeypatch.setattr(ocr, "perform_ocr", lambda img, sf=1.0: [
        {"text": "Hello there", "rect": (0, 0, 100, 20)}])
    errors, results = _run(worker_mod.TranslationWorker(BLANK))
    assert errors == [] and len(results[0]) == 1


def test_window_shows_worker_error_in_toast(qapp, monkeypatch):
    win = ui.MainWindow()
    win.show()
    monkeypatch.setattr(worker_mod.TranslationWorker, "start", lambda self: None)
    monkeypatch.setattr(win, "get_capture_geometry", lambda: (_FakeScreen(), 0, 0, 10, 10))
    win._do_grab()
    win.worker.error.emit("Tesseract is not installed")
    win.worker.finished_translation.emit([])
    qapp.processEvents()
    assert win.central.status_label.isVisible()
    assert win.central.status_label.text() == "Tesseract is not installed"
    win.worker = None
    win.close()


class _FakeScreen:
    def devicePixelRatio(self):
        return 1.0

    def grabWindow(self, wid, x, y, w, h):
        pm = QtGui.QPixmap(w, h)
        pm.fill(QtGui.QColor(255, 255, 255))
        return pm


def test_newer_toast_not_hidden_by_older_timer(qapp):
    win = ui.MainWindow()
    win.show()
    win.central.show_status("first", 50)
    win.central.show_status("second", 1000)
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        qapp.processEvents()
    assert win.central.status_label.isVisible()
    assert win.central.status_label.text() == "second"
    win.close()


def test_toast_hides_after_duration(qapp):
    win = ui.MainWindow()
    win.show()
    win.central.show_status("x", 50)
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        qapp.processEvents()
    assert not win.central.status_label.isVisible()
    win.close()
