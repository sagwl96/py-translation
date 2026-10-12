"""Qt widgets and the main (transparent) window."""

from PyQt6 import QtCore, QtGui, QtWidgets

from .capture import qimage_to_bgr
from . import render
from .config import CONFIG
from .worker import TranslationWorker

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

class OverlayLabel(QtWidgets.QLabel):
    """Translated-text label; a left click emits `clicked` (used to copy the text)."""
    clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plain_text = ""
        # Translations are plain text; never let Qt guess rich text (quotes, &, < would break)
        self.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to copy")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)


class TransparentCentralWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0);")
        self.status_label = QtWidgets.QLabel(self)
        self.status_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: white; background-color: rgba(0,0,0,150); padding: 4px; border-radius: 4px;")
        self.status_label.hide()
        # One timer per label: a newer show_status restarts it, so an older
        # call's timeout can never hide a newer message.
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self.status_label.hide)

    def paintEvent(self, event):
        pass

    def show_status(self, text, duration=2000):
        self.status_label.setText(text)
        self.status_label.adjustSize()
        self.status_label.move((self.width() - self.status_label.width()) // 2,
                               self.height() - self.status_label.height() - 20)
        self.status_label.show()
        self.status_label.raise_()   # overlays are siblings; keep the toast above them
        self._status_timer.start(duration)

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
        if CONFIG.on_top:
            self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)

        self.spinner_overlay = None
        self.worker = None
        self.overlay_labels = []
        self._capture_pending = False
        self._error_shown = False

    def get_transparent_area_geometry(self):
        geom = self.central.geometry()
        global_top_left = self.mapToGlobal(geom.topLeft())
        return global_top_left.x(), global_top_left.y(), geom.width(), geom.height()

    def get_capture_geometry(self):
        """Return (screen, x, y, w, h) with x, y relative to the screen the window is on."""
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        gx, gy, w, h = self.get_transparent_area_geometry()
        origin = screen.geometry().topLeft()
        return screen, gx - origin.x(), gy - origin.y(), w, h

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
        """Prepare a capture: hide our own UI, then grab after the compositor repaints."""
        if (self.worker is not None and self.worker.isRunning()) or self._capture_pending:
            return

        self._capture_pending = True
        self.clearOverlays()
        self.hideSpinner()
        self.central.status_label.hide()
        QtWidgets.QApplication.processEvents()
        QtCore.QTimer.singleShot(CONFIG.capture_delay_ms, self._do_grab)

    def _do_grab(self):
        self._capture_pending = False
        self._error_shown = False
        screen, x, y, w, h = self.get_capture_geometry()
        screenshot = screen.grabWindow(0, x, y, w, h)
        qimage = screenshot.toImage()
        img_bgr = qimage_to_bgr(qimage)

        self.showSpinner()
        self.central.show_status("OCR + Translating...", 3000)

        self.worker = TranslationWorker(img_bgr, dpr=screen.devicePixelRatio())
        self.worker.finished_translation.connect(self.on_translation_finished)
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    @QtCore.pyqtSlot(str)
    def on_worker_error(self, message):
        self._error_shown = True
        self.hideSpinner()
        self.central.show_status(message, 5000)

    @QtCore.pyqtSlot(list)
    def on_translation_finished(self, result_data):
        self.hideSpinner()

        if not result_data:
            if self._error_shown:
                return   # keep the specific error message visible
            self.central.show_status("No text found or translation failed.", 2000)
            return

        self.central.show_status(f"Translated {len(result_data)} paragraphs.", 1500)

        boxes = []
        for item in result_data:
            px, py, pw, ph = item['par_rect']
            text_h = item.get('text_h')
            if not text_h:
                line_rects = item.get('line_rects')
                text_h = sum(r[3] for r in line_rects) / len(line_rects) if line_rects else ph
            # Label = source rect + a little margin: it neither grows past the source
            # area nor leaves original text showing around it.
            boxes.append((px - render.GROW, py - render.GROW, pw + 2 * render.GROW, ph + 2 * render.GROW, text_h))
        # Neighbouring (grown) rects must not overlap each other.
        rects = render.resolve_overlaps([b[:4] for b in boxes])

        for item, box, (lx, ly, lw, lh) in zip(result_data, boxes, rects):
            text_h = box[4]
            text = item['text']
            if text is None:
                text = ""
            if lw <= 0 or lh <= 0:
                continue
            inner_w = lw - 2 * (render.PAD + 1) - render.WIDTH_SLACK   # QLabel wraps a hair earlier than QFontMetrics
            inner_h = lh - 2 * render.PAD + render.LINE_SLACK * text_h
            shown = text.replace('\n', ' ')
            font_px = render.fit_font_px(shown, inner_w, inner_h, text_h * render.TEXT_H_TO_PX)
            elided = render.elide_to_fit(shown, inner_w, inner_h, font_px)

            label = OverlayLabel(self.central)
            label.plain_text = text
            label.font_px = font_px
            label.clicked.connect(lambda lbl=label: self.copy_overlay_text(lbl))
            label.setFont(render.make_font(font_px))
            label.setText(elided)
            if elided != shown:
                label.setToolTip(text + "\n(click to copy)")
            label.setWordWrap(True)
            _, th = render.text_size(elided, inner_w, font_px)
            single = th <= QtGui.QFontMetrics(label.font()).lineSpacing() * 1.5
            label.setAlignment((QtCore.Qt.AlignmentFlag.AlignVCenter if single else QtCore.Qt.AlignmentFlag.AlignTop)
                               | QtCore.Qt.AlignmentFlag.AlignLeft)
            bg = tuple(item.get('bg') or render.DEFAULT_BG)
            fg = render.pick_text_color(bg)
            label.setStyleSheet(f"""
                QLabel {{
                    background-color: rgb({bg[0]}, {bg[1]}, {bg[2]});
                    color: rgb({fg[0]}, {fg[1]}, {fg[2]});
                    padding: {render.PAD}px {render.PAD + 1}px;
                    border-radius: 3px;
                }}
            """)
            label.setGeometry(lx, ly, lw, lh)

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
        # Overlays created after the "Translated N paragraphs" toast would cover it
        self.central.status_label.raise_()

    def copy_overlay_text(self, label):
        QtWidgets.QApplication.clipboard().setText(label.plain_text)
        self.central.show_status("Copied", 1000)

    def _worker_finished(self):
        if self.worker is not None:
            self.worker.deleteLater()
            QtCore.QTimer.singleShot(0, self._clear_worker)

    def _clear_worker(self):
        self.worker = None

    def toggle_always_on_top(self):
        """Flip WindowStaysOnTopHint; Qt hides the window on a flag change, so re-show it in place."""
        on = not bool(self.windowFlags() & QtCore.Qt.WindowType.WindowStaysOnTopHint)
        was_visible = self.isVisible()
        geom = self.geometry()
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, on)
        if was_visible:
            self.show()
        self.setGeometry(geom)
        self.central.show_status(f"Always on top: {'on' if on else 'off'}", 1500)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Space:
            self.capture_transparent_area()
        elif event.key() == QtCore.Qt.Key.Key_Escape:
            self.clearOverlays()
            self.central.show_status("Overlays cleared.", 1000)
        elif event.key() == QtCore.Qt.Key.Key_T:
            self.toggle_always_on_top()
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
            self.worker.requestInterruption()
            self.worker.wait(2000)
        event.accept()
