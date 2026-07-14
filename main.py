#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import cv2
import numpy as np
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import hashlib

from PyQt6 import QtCore, QtWidgets, QtGui

# Optional high-performance libraries, fallback if missing
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False

try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_AVAILABLE = True
except ImportError:
    ARGOS_AVAILABLE = False

# Fallback for translation
from deep_translator import GoogleTranslator

# Fallback OCR
import pytesseract

# Global configuration
TARGET_LANG = 'en'
USE_OFFLINE_TRANSLATION = True
USE_PADDLE_OCR = False
MAX_OCR_WIDTH = 1280
_ARGOS_INSTALLED = False

# High-DPI support, safe for Qt6
try:
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
except AttributeError:
    pass

class ModernSpinner(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 60)
        self.angle = 0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.rotate)
        self.timer.start(15)

    def rotate(self):
        self.angle = (self.angle + 6) % 360
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        draw_rect = QtCore.QRectF(10, 10, 40, 40)

        pen_bg = QtGui.QPen(QtGui.QColor(220, 220, 220, 50), 6)
        pen_bg.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_bg)
        painter.drawArc(draw_rect, 0, 360 * 16)

        pen_fg = QtGui.QPen(QtGui.QColor(41, 121, 255), 6)
        pen_fg.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_fg)
        span_angle = 120 * 16
        start_angle = -self.angle * 16
        painter.drawArc(draw_rect, start_angle, span_angle)

class OverlaySpinner(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setGeometry(parent.rect())
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0.4);")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.spinner = ModernSpinner(self)
        layout.addWidget(self.spinner)

class TransparentCentralWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
        self.status_label = QtWidgets.QLabel(self)
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: white; background-color: rgba(0,0,0,150); padding: 4px; border-radius: 4px;")
        self.status_label.hide()

    def paintEvent(self, event):
        pass

    def show_status(self, text, duration=2000):
        self.status_label.setText(text)
        self.status_label.adjustSize()
        self.status_label.move((self.width() - self.status_label.width()) // 2,
                               self.height() - self.status_label.height() - 20)
        self.status_label.show()
        QtCore.QTimer.singleShot(duration, self.status_label.hide)

class TranslationWorker(QtCore.QThread):
    finished_translation = QtCore.pyqtSignal(list)
    _paddle_ocr = None

    def __init__(self, img_bgr, parent=None):
        super().__init__(parent)
        self.img_bgr = img_bgr
        self.scale_factor = 1.0

    def run(self):
        try:
            img_processed = self._preprocess_image(self.img_bgr)
            ocr_lines = self._perform_ocr(img_processed)
            
            if not ocr_lines:
                self.finished_translation.emit([])
                return
                
            paragraphs = self._group_lines_to_paragraphs(ocr_lines)
            translated_paragraphs = self._translate_paragraphs(paragraphs)

            result_data = []
            for par in translated_paragraphs:
                result_data.append({
                    'text': par['text'],
                    'par_rect': par['par_rect'],
                    'line_rects': par['line_rects']
                })

            self.finished_translation.emit(result_data)

        except Exception as e:
            print("Worker Exception:", e)
            self.finished_translation.emit([])

    def _preprocess_image(self, img):
        if MAX_OCR_WIDTH <= 0:
            return img
        h, w = img.shape[:2]
        if w > MAX_OCR_WIDTH:
            self.scale_factor = MAX_OCR_WIDTH / w
            new_w = int(w * self.scale_factor)
            new_h = int(h * self.scale_factor)
            return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return img

    def _perform_ocr(self, img):
        if USE_PADDLE_OCR and PADDLE_AVAILABLE:
            try:
                lines = self._ocr_paddle(img)
                if lines:
                    return lines
            except Exception as e:
                print("PaddleOCR failed, falling back to Tesseract:", e)
        return self._ocr_tesseract(img)

    def _ocr_paddle(self, img):
        if TranslationWorker._paddle_ocr is None:
            params = {'lang': 'en'}
            try:
                import inspect
                sig = inspect.signature(PaddleOCR.__init__)
                if 'use_textline_orientation' in sig.parameters:
                    params['use_textline_orientation'] = False
                if 'log_level' in sig.parameters:
                    params['log_level'] = 'ERROR'
                if 'use_gpu' in sig.parameters:
                    params['use_gpu'] = False
            except Exception:
                pass
            try:
                TranslationWorker._paddle_ocr = PaddleOCR(**params)
            except TypeError:
                TranslationWorker._paddle_ocr = PaddleOCR(lang='en')

        ocr = TranslationWorker._paddle_ocr
        result = ocr.ocr(img, cls=False)
        lines = []
        scale_back = 1.0 / self.scale_factor

        if result and result[0]:
            for line in result[0]:
                bbox = line[0]
                text = line[1][0] if isinstance(line[1], tuple) else line[1]
                text = text.strip()
                if not text:
                    continue
                
                xs = [pt[0] for pt in bbox]
                ys = [pt[1] for pt in bbox]
                min_x = int(min(xs) * scale_back)
                max_x = int(max(xs) * scale_back)
                min_y = int(min(ys) * scale_back)
                max_y = int(max(ys) * scale_back)
                
                lines.append({
                    'text': text,
                    'rect': (min_x, min_y, max_x - min_x, max_y - min_y),
                })
        return lines

    def _ocr_tesseract(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        lang_combinations = ['eng+deu', 'eng', 'deu']
        lines = []
        data = None
        
        for lang in lang_combinations:
            try:
                data = pytesseract.image_to_data(gray, lang=lang, output_type=pytesseract.Output.DICT)
                if any(text.strip() for text in data['text']):
                    break
            except pytesseract.TesseractNotFoundError:
                print("Tesseract not installed or not in PATH.")
                return []
            except Exception:
                continue
        else:
            return []

        scale_back = 1.0 / self.scale_factor
        
        line_dict = {}
        for i in range(len(data['text'])):
            text = data['text'][i].strip()
            if not text:
                continue
            
            b_num = data['block_num'][i]
            p_num = data['par_num'][i]
            l_num = data['line_num'][i]
            key = (b_num, p_num, l_num)
            
            x = int(data['left'][i] * scale_back)
            y = int(data['top'][i] * scale_back)
            w = int(data['width'][i] * scale_back)
            h = int(data['height'][i] * scale_back)
            
            if key not in line_dict:
                line_dict[key] = {'text': [], 'rects': []}
                
            line_dict[key]['text'].append(text)
            line_dict[key]['rects'].append((x, y, w, h))
            
        for key in sorted(line_dict.keys()):
            words = line_dict[key]['text']
            rects = line_dict[key]['rects']
            
            line_text = " ".join(words)
            min_x = min(r[0] for r in rects)
            min_y = min(r[1] for r in rects)
            max_x = max(r[0] + r[2] for r in rects)
            max_y = max(r[1] + r[3] for r in rects)
            
            lines.append({
                'text': line_text,
                'rect': (min_x, min_y, max_x - min_x, max_y - min_y)
            })

        return lines

    def _group_lines_to_paragraphs(self, lines):
        if not lines:
            return []
        lines_sorted = sorted(lines, key=lambda l: (l['rect'][1], l['rect'][0]))
        paragraphs = []
        current_paragraph = []
        avg_height = np.mean([l['rect'][3] for l in lines_sorted]) if lines_sorted else 20
        vertical_threshold = avg_height * 1.2
        horizontal_overlap_threshold = 0.5

        for line in lines_sorted:
            x, y, w, h = line['rect']
            if not current_paragraph:
                current_paragraph.append(line)
                continue
            last_x, last_y, last_w, last_h = current_paragraph[-1]['rect']
            gap = y - (last_y + last_h)
            
            if gap < vertical_threshold and self._horizontal_overlap((x, w), (last_x, last_w)) > horizontal_overlap_threshold:
                current_paragraph.append(line)
            else:
                paragraphs.append(self._make_paragraph(current_paragraph))
                current_paragraph = [line]
                
        if current_paragraph:
            paragraphs.append(self._make_paragraph(current_paragraph))

        return paragraphs

    def _horizontal_overlap(self, rect1, rect2):
        x1, w1 = rect1
        x2, w2 = rect2
        left = max(x1, x2)
        right = min(x1 + w1, x2 + w2)
        if right <= left:
            return 0
        overlap = right - left
        min_width = min(w1, w2)
        return overlap / min_width if min_width > 0 else 0

    def _make_paragraph(self, lines):
        full_text = " ".join([l['text'] for l in lines])
        line_rects = [l['rect'] for l in lines]
        xs = [r[0] for r in line_rects]
        ys = [r[1] for r in line_rects]
        x2s = [r[0] + r[2] for r in line_rects]
        y2s = [r[1] + r[3] for r in line_rects]
        par_rect = (min(xs), min(ys), max(x2s) - min(xs), max(y2s) - min(ys))
        return {
            'text': full_text,
            'par_rect': par_rect,
            'line_rects': line_rects
        }

    def _translate_paragraphs(self, paragraphs):
        if not paragraphs:
            return paragraphs
        for par in paragraphs:
            original_text = par['text']
            if not original_text:
                par['text'] = ""
                continue
            try:
                par['text'] = self._translate_text(original_text, 'de')
            except Exception as e:
                print("Translation error:", e)
                par['text'] = original_text
        return paragraphs

    def _translate_text(self, text, src_lang='de'):
        if USE_OFFLINE_TRANSLATION and ARGOS_AVAILABLE:
            return self._translate_argos(text, src_lang)
        else:
            return self._translate_google(text)

    def _translate_argos(self, text, src_lang):
        global _ARGOS_INSTALLED

        if not _ARGOS_INSTALLED:
            try:
                argostranslate.package.update_package_index()
                available = argostranslate.package.get_available_packages()
                target_pkg = next((pkg for pkg in available if pkg.from_code == src_lang and pkg.to_code == TARGET_LANG), None)
                
                if target_pkg:
                    pkg_path = target_pkg.download()
                    argostranslate.package.install_from_path(pkg_path)
                    _ARGOS_INSTALLED = True
                else:
                    _ARGOS_INSTALLED = False
            except Exception:
                _ARGOS_INSTALLED = False

        if _ARGOS_INSTALLED:
            try:
                return argostranslate.translate.translate(text, src_lang, TARGET_LANG)
            except Exception:
                return self._translate_google(text)
        else:
            return self._translate_google(text)

    def _translate_google(self, text):
        try:
            translator = GoogleTranslator(source='auto', target=TARGET_LANG)
            return translator.translate(text)
        except Exception:
            return text

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Instant Translator (Performance Edition)")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.central = TransparentCentralWidget(self)
        self.setCentralWidget(self.central)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.central.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.resize(800, 600)

        self.spinner_overlay = None
        self.worker = None
        self.overlay_labels = []

    def get_transparent_area_geometry(self):
        geom = self.central.geometry()
        global_top_left = self.mapToGlobal(geom.topLeft())
        return global_top_left.x(), global_top_left.y(), geom.width(), geom.height()

    def showSpinner(self):
        self.clearOverlays()
        if self.spinner_overlay is not None:
            self.spinner_overlay.hide()
            self.spinner_overlay.deleteLater()
        self.spinner_overlay = OverlaySpinner(self.central)
        self.spinner_overlay.show()
        self.spinner_overlay.raise_()

    def hideSpinner(self):
        if self.spinner_overlay is not None:
            self.spinner_overlay.hide()
            self.spinner_overlay.deleteLater()
            self.spinner_overlay = None

    def clearOverlays(self):
        for label in self.overlay_labels:
            label.hide()
            label.deleteLater()
        self.overlay_labels.clear()

    def capture_transparent_area(self):
        if self.worker is not None and self.worker.isRunning():
            return

        self.clearOverlays()
        self.central.show_status("Capturing...", 1000)

        screen = QtWidgets.QApplication.primaryScreen()
        x, y, w, h = self.get_transparent_area_geometry()
        screenshot = screen.grabWindow(0, x, y, w, h)
        qimage = screenshot.toImage()
        ptr = qimage.bits()
        ptr.setsize(qimage.sizeInBytes())
        img_rgba = np.array(ptr).reshape((qimage.height(), qimage.width(), 4))
        img_bgr = cv2.cvtColor(img_rgba, cv2.COLOR_RGBA2BGR)

        self.showSpinner()
        self.central.show_status("OCR + Translating...", 3000)

        self.worker = TranslationWorker(img_bgr)
        self.worker.finished_translation.connect(self.on_translation_finished)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    @QtCore.pyqtSlot(list)
    def on_translation_finished(self, result_data):
        self.hideSpinner()

        if not result_data:
            self.central.show_status("No text found or translation failed.", 2000)
            return

        self.central.show_status(f"Translated {len(result_data)} paragraphs.", 1500)

        for item in result_data:
            text = item['text']
            if text is None:
                text = ""
                
            px, py, pw, ph = item['par_rect']
            line_rects = item['line_rects']

            if line_rects:
                avg_lh = sum([r[3] for r in line_rects]) / len(line_rects)
                font_size = max(11, int(avg_lh * 0.73))
            else:
                font_size = 14

            label = QtWidgets.QLabel(self.central)
            safe_text = html.escape(text.replace('\n', ' '))
            
            label.setText(safe_text)
            label.setWordWrap(True)
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
            
            label.setStyleSheet(f"""
                QLabel {{
                    background-color: rgba(252, 250, 222, 230);
                    color: #111111;
                    font-size: {font_size}px;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    font-weight: 500;
                    padding: 4px;
                    border-radius: 4px;
                }}
            """)
            
            label.setGeometry(px, py, pw, 1000)
            label.setFixedWidth(pw)
            label.adjustSize()
            
            effect = QtWidgets.QGraphicsOpacityEffect(label)
            label.setGraphicsEffect(effect)
            anim = QtCore.QPropertyAnimation(effect, b"opacity")
            anim.setDuration(300)
            anim.setStartValue(0)
            anim.setEndValue(1)
            anim.start(QtCore.QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            
            label.show()
            label.anim_ref = anim
            self.overlay_labels.append(label)

    def _worker_finished(self):
        if self.worker is not None:
            self.worker.deleteLater()
            QtCore.QTimer.singleShot(0, self._clear_worker)

    def _clear_worker(self):
        self.worker = None

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Space:
            self.capture_transparent_area()
        elif event.key() == QtCore.Qt.Key.Key_Escape:
            self.clearOverlays()
            self.central.show_status("Overlays cleared.", 1000)
        elif event.key() == QtCore.Qt.Key.Key_Alt:
            for label in self.overlay_labels:
                label.hide()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Alt:
            for label in self.overlay_labels:
                label.show()
        else:
            super().keyReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.spinner_overlay:
            self.spinner_overlay.setGeometry(self.central.rect())

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.quit()
            self.worker.wait()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())