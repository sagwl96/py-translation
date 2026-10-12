"""Background thread: preprocess -> OCR -> group -> translate -> emit."""
import copy
import hashlib
import threading

import cv2
from PyQt6 import QtCore

from . import debug, ocr, translate
from .capture import sample_background, scale_rects
from .config import CONFIG
from .layout import group_lines_to_paragraphs


_last_capture = None   # (key, result_data) of the last successful capture
_last_lock = threading.Lock()


def clear_capture_cache():
    global _last_capture
    with _last_lock:
        _last_capture = None


def capture_key(img_bgr, dpr=1.0):
    """Hash of a 4x downsampled grayscale capture plus every setting that changes the result."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    h = hashlib.blake2b(small.tobytes(), digest_size=16)
    h.update(repr((gray.shape, dpr, CONFIG.source_lang, CONFIG.target_lang, CONFIG.min_ocr_conf,
                   CONFIG.ocr_lang, CONFIG.offline)).encode())
    return h.digest()


class TranslationWorker(QtCore.QThread):
    finished_translation = QtCore.pyqtSignal(list)
    error = QtCore.pyqtSignal(str)

    def __init__(self, img_bgr, parent=None, dpr=1.0):
        super().__init__(parent)
        self.img_bgr = img_bgr
        self.dpr = dpr

    def run(self):
        global _last_capture
        try:
            dpr = getattr(self, 'dpr', 1.0)
            key = capture_key(self.img_bgr, dpr)
            with _last_lock:
                hit = _last_capture[1] if _last_capture and _last_capture[0] == key else None
            if hit is not None:   # same screen content and settings: skip OCR and translation
                self._save(dpr, cache_hit=True, result=hit)
                self.finished_translation.emit(copy.deepcopy(hit))
                return

            img_processed, scale_factor = self._preprocess_image(self.img_bgr)
            ocr_lines = self._perform_ocr(img_processed, scale_factor)

            if self.isInterruptionRequested():
                self.finished_translation.emit([])
                return

            if not ocr_lines:
                self._save(dpr, ocr_lines=[], result=[])
                self.finished_translation.emit([])
                return

            paragraphs = group_lines_to_paragraphs(ocr_lines)
            source_paragraphs = copy.deepcopy(paragraphs) if CONFIG.save_captures else None
            report = translate.TranslationReport()
            translated_paragraphs = self._translate_paragraphs(paragraphs, report)
            if report.all_failed:
                self.error.emit("Translation failed: " + report.errors[0])

            result_data = []
            for par in translated_paragraphs:
                result_data.append({
                    'text': par['text'],
                    'par_rect': scale_rects([par['par_rect']], dpr)[0],
                    'line_rects': scale_rects(par['line_rects'], dpr),
                    'bg': sample_background(self.img_bgr, par['par_rect']),
                    'text_h': par.get('text_h', par['par_rect'][3]) / (dpr or 1.0),
                })

            self._save(dpr, ocr_lines=ocr_lines, paragraphs=source_paragraphs,
                       translated=[p['text'] for p in translated_paragraphs],
                       errors=report.errors, result=result_data)
            if not report.errors and not self.isInterruptionRequested():
                with _last_lock:
                    _last_capture = (key, copy.deepcopy(result_data))
            self.finished_translation.emit(result_data)

        except Exception as e:
            print("Worker Exception:", e)
            self._save(getattr(self, 'dpr', 1.0), error=repr(e))
            self.error.emit(str(e) or type(e).__name__)
            self.finished_translation.emit([])

    def _save(self, dpr, **info):
        if CONFIG.save_captures:
            debug.save_capture(CONFIG.save_captures, self.img_bgr, dpr=dpr, **info)

    def _preprocess_image(self, img):
        return ocr.preprocess_image(img)

    def _perform_ocr(self, img, scale_factor=1.0):
        return ocr.perform_ocr(img, scale_factor)

    def _translate_paragraphs(self, paragraphs, report=None):
        return translate.translate_paragraphs(paragraphs, self.isInterruptionRequested, report)
