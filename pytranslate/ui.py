"""Qt widgets and the main window: a frameless, see-through "floating frame" with a pill toolbar."""
import math

from PyQt6 import QtCore, QtGui, QtWidgets

from . import geometry as geo
from . import icons, render, theme, translate, worker as worker_mod
from .capture import qimage_to_bgr
from .config import CONFIG
from .theme import qcolor
from .worker import TranslationWorker

Qt = QtCore.Qt
_AA = QtGui.QPainter.RenderHint.Antialiasing
_NOPEN = Qt.PenStyle.NoPen
_NOBRUSH = Qt.BrushStyle.NoBrush

_CURSORS = {
    frozenset("l"): Qt.CursorShape.SizeHorCursor, frozenset("r"): Qt.CursorShape.SizeHorCursor,
    frozenset("t"): Qt.CursorShape.SizeVerCursor, frozenset("b"): Qt.CursorShape.SizeVerCursor,
    frozenset("lt"): Qt.CursorShape.SizeFDiagCursor, frozenset("rb"): Qt.CursorShape.SizeFDiagCursor,
    frozenset("rt"): Qt.CursorShape.SizeBDiagCursor, frozenset("lb"): Qt.CursorShape.SizeBDiagCursor,
}


def edges_to_qt(edges):
    flags = Qt.Edge(0)
    for e, q in (("l", Qt.Edge.LeftEdge), ("r", Qt.Edge.RightEdge),
                 ("t", Qt.Edge.TopEdge), ("b", Qt.Edge.BottomEdge)):
        if e in edges:
            flags |= q
    return flags


def ui_font(px, weight=QtGui.QFont.Weight.Normal):
    f = QtGui.QFont()
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def _anim(parent, ms, start=0.0, end=1.0, easing=QtCore.QEasingCurve.Type.Linear):
    a = QtCore.QVariantAnimation(parent)
    a.setDuration(ms)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(easing)
    return a


def make_menu(parent):
    """A dark rounded QMenu (translucent frameless popup so the corners can be round)."""
    m = QtWidgets.QMenu(parent)
    m.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    m.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    m.setStyleSheet(theme.MENU_QSS)
    return m


# --------------------------------------------------------------------------- overlays

class OverlayLabel(QtWidgets.QLabel):
    """Translated-text label; a left click emits `clicked` (used to copy the text)."""
    clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plain_text = ""
        self._hover = False
        self._ring = 0.0            # copy-flash ring strength, 0..1
        self._ring_anim = None
        # Translations are plain text; never let Qt guess rich text (quotes, &, < would break)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to copy")

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def flash_ring(self):
        """Brief accent ring after the text was copied."""
        if self._ring_anim is not None:
            self._ring_anim.stop()
        a = _anim(self, 450, 1.0, 0.0, QtCore.QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(self._set_ring)
        self._ring_anim = a
        self._ring = 1.0
        a.start()

    def _set_ring(self, v):
        self._ring = float(v)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        strength = max(1.0 if self._hover else 0.0, self._ring)
        if strength <= 0:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(_AA)
        p.setBrush(_NOBRUSH)
        p.setPen(QtGui.QPen(qcolor(theme.ACCENT, 255 * strength), 1.5))
        r = QtCore.QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        p.drawRoundedRect(r, theme.OVERLAY_RADIUS, theme.OVERLAY_RADIUS)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)


class CaptureArea(QtWidgets.QWidget):
    """The area inside the frame: transparent parent of the overlay labels."""

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        self._labels = labels
        self.setCursor(Qt.CursorShape.ArrowCursor)


# --------------------------------------------------------------------------- toolbar

class IconButton(QtWidgets.QAbstractButton):
    """28x28 round icon button: hover/pressed tint, optional toggled and busy (spinner) state."""

    def __init__(self, icon_name, tooltip, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setToolTip(tooltip)
        self.setFixedSize(theme.BUTTON, theme.BUTTON)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(False)
        self.toggled_on = False
        self._busy = False
        self._angle = 0.0
        self._spin = _anim(self, 900, 0.0, 360.0)
        self._spin.setLoopCount(-1)
        self._spin.valueChanged.connect(self._set_angle)

    def is_busy(self):
        return self._busy

    def set_busy(self, busy):
        busy = bool(busy)
        if busy == self._busy:
            return
        self._busy = busy
        if busy:
            self._spin.start()
        else:
            self._spin.stop()
        self.update()

    def set_toggled(self, on):
        self.toggled_on = bool(on)
        self.update()

    def _set_angle(self, v):
        self._angle = float(v)
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(_AA)
        p.setPen(_NOPEN)
        c = QtCore.QRectF(self.rect())
        if self.toggled_on:
            tint = 90 if self.isDown() else (72 if self.underMouse() else 56)
            p.setBrush(qcolor(theme.ACCENT, tint))
        elif self.isDown():
            p.setBrush(qcolor(theme.WHITE, 41))
        elif self.underMouse():
            p.setBrush(qcolor(theme.WHITE, 26))
        else:
            p.setBrush(_NOBRUSH)
        p.drawRoundedRect(c, c.width() / 2, c.height() / 2)
        if self._busy:
            self._paint_spinner(p, c)
            return
        color = theme.ACCENT_HOVER if self.toggled_on else theme.INK
        s = theme.ICON
        icons.draw_icon(p, self.icon_name, QtCore.QRectF(c.center().x() - s / 2, c.center().y() - s / 2, s, s), color)

    def _paint_spinner(self, p, c):
        r = QtCore.QRectF(c.center().x() - 7, c.center().y() - 7, 14, 14)
        pen = QtGui.QPen(qcolor(theme.WHITE, 36), 2)
        p.setPen(pen)
        p.setBrush(_NOBRUSH)
        p.drawEllipse(r)
        pen = QtGui.QPen(QtGui.QColor(theme.ACCENT_HOVER), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, int(-self._angle * 16), 100 * 16)


class GripButton(QtWidgets.QWidget):
    """Drag handle: pressing it starts a system window move."""
    pressed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(theme.BUTTON - 4, theme.BUTTON)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("Drag to move")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit()
            event.accept()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(_AA)
        p.setPen(_NOPEN)
        p.setBrush(qcolor(theme.INK, 200 if self.underMouse() else 140))
        cx, cy = self.width() / 2, self.height() / 2
        for col in (-2.5, 2.5):
            for row in (-5, 0, 5):
                p.drawEllipse(QtCore.QPointF(cx + col, cy + row), 1.2, 1.2)


class LangChip(QtWidgets.QAbstractButton):
    """Accent pill showing "Auto → EN"; a click asks the window to open the language menu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Source language")
        self._font = ui_font(12, QtGui.QFont.Weight.Medium)
        self.setHeight()

    def setHeight(self):
        self.setFixedHeight(theme.BUTTON)

    def setText(self, text):
        super().setText(text)
        w = QtGui.QFontMetrics(self._font).horizontalAdvance(text) + 12 + 5 + 10 + 4
        self.setFixedWidth(w)
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(_AA)
        r = QtCore.QRectF(0, (self.height() - 22) / 2, self.width(), 22)
        p.setPen(_NOPEN)
        bg = QtGui.QColor(theme.ACCENT_DEEP)
        if self.isDown():
            bg = bg.darker(115)
        elif self.underMouse():
            bg = bg.lighter(115)
        p.setBrush(bg)
        p.drawRoundedRect(r, 11, 11)
        p.setFont(self._font)
        p.setPen(QtGui.QColor(theme.CHIP_TEXT))
        p.drawText(QtCore.QRectF(r.left() + 10, r.top(), r.width() - 10 - 17, r.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        icons.draw_icon(p, "chevron", QtCore.QRectF(r.right() - 17, r.center().y() - 5, 10, 10), theme.CHIP_TEXT)


class Toolbar(QtWidgets.QWidget):
    """The pill: grip, language chip, translate, clear, pin, more, close."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.grip = GripButton(self)
        self.chip = LangChip(self)
        self.translate_btn = IconButton("language", "Translate · Space", self)
        self.clear_btn = IconButton("eraser", "Clear · Esc", self)
        self.pin_btn = IconButton("pin", "Always on top · T", self)
        self.more_btn = IconButton("dots", "More", self)
        self.close_btn = IconButton("x", "Close", self)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, (theme.PILL_H - theme.BUTTON) // 2, 4, (theme.PILL_H - theme.BUTTON) // 2)
        lay.setSpacing(theme.GAP)
        for w in (self.grip, self.chip, self.translate_btn, self.clear_btn, self.pin_btn,
                  self.more_btn, self.close_btn):
            lay.addWidget(w)
        self.chip.setText("Auto → EN")
        lay.activate()
        self.setFixedSize(lay.sizeHint().width(), theme.PILL_H)

    def refit(self):
        self.layout().activate()
        self.setFixedWidth(self.layout().sizeHint().width())

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(_AA)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(qcolor(theme.PILL_BG, theme.PILL_ALPHA))
        p.setPen(QtGui.QPen(qcolor(theme.WHITE, 26), 1))
        p.drawRoundedRect(r, theme.PILL_RADIUS - 0.5, theme.PILL_RADIUS - 0.5)


# --------------------------------------------------------------------------- floating pills

class HintPill(QtWidgets.QWidget):
    """Idle hint in the middle of the capture area; fades in and out."""
    LINE1 = "Press Space to translate"
    LINE2 = "Drag the frame to move · edges to resize"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._f1 = ui_font(13, QtGui.QFont.Weight.Medium)
        self._f2 = ui_font(12)
        m1, m2 = QtGui.QFontMetrics(self._f1), QtGui.QFontMetrics(self._f2)
        w = max(m1.horizontalAdvance(self.LINE1), m2.horizontalAdvance(self.LINE2)) + 2 * 22
        h = 2 * 14 + m1.height() + 3 + m2.height()
        self.setFixedSize(w, h)
        self._opacity = 1.0
        self._anim = _anim(self, theme.HINT_FADE_MS)
        self._anim.valueChanged.connect(self._set_opacity)
        self._anim.finished.connect(self._done)
        self._target = 1.0
        self.hide()

    def opacity(self):
        return self._opacity

    def _set_opacity(self, v):
        self._opacity = float(v)
        self.update()

    def _done(self):
        if self._target <= 0:
            self.hide()

    def fade_to(self, target):
        self._anim.stop()
        self._target = float(target)
        if target > 0 and not self.isVisible():
            self._opacity = 0.0
            self.show()
        elif target <= 0 and not self.isVisible():
            return
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(self._target)
        self._anim.start()

    def hide_now(self):
        self._anim.stop()
        self._target = 0.0
        self._opacity = 0.0
        self.hide()

    def show_now(self):
        self._anim.stop()
        self._target = 1.0
        self._opacity = 1.0
        self.show()
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(_AA)
        p.setOpacity(self._opacity)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(qcolor(theme.PILL_BG, theme.HINT_ALPHA))
        p.setPen(QtGui.QPen(qcolor(theme.WHITE, 26), 1))
        p.drawRoundedRect(r, 14, 14)
        m1, m2 = QtGui.QFontMetrics(self._f1), QtGui.QFontMetrics(self._f2)
        y = 14
        p.setFont(self._f1)
        p.setPen(QtGui.QColor(theme.INK))
        p.drawText(QtCore.QRectF(0, y, self.width(), m1.height()), int(Qt.AlignmentFlag.AlignCenter), self.LINE1)
        p.setFont(self._f2)
        p.setPen(qcolor(theme.INK, 178))
        p.drawText(QtCore.QRectF(0, y + m1.height() + 3, self.width(), m2.height()),
                   int(Qt.AlignmentFlag.AlignCenter), self.LINE2)


class Toast(QtWidgets.QLabel):
    """Dark pill message; error toasts carry a coral dot."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(ui_font(13))
        self.setStyleSheet(f"color: {theme.INK}; background: transparent;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.error = False
        self._opacity = 1.0
        self.hide()

    def opacity(self):
        return self._opacity

    def set_opacity(self, v):
        self._opacity = float(v)
        self.update()

    def natural_width(self, text, error):
        left = 16 + (14 if error else 0)
        return QtGui.QFontMetrics(self.font()).horizontalAdvance(text) + left + 16 + 2

    def set_message(self, text, error, max_width, fixed_h=None):
        """Size the toast. fixed_h: one line, exactly that tall (toolbar-row mode); otherwise
        word-wrapped to max_width."""
        self.error = bool(error)
        self.setText(text)
        left = 16 + (14 if error else 0)
        vm = 0 if fixed_h else 8
        self.setContentsMargins(left, vm, 16, vm)
        natural = self.natural_width(text, error)
        if fixed_h:
            self.setWordWrap(False)
            self.setFixedSize(natural, fixed_h)
            return
        self.setWordWrap(True)
        w = max(40, min(natural, max_width))
        self.setFixedWidth(w)
        self.setFixedHeight(self.heightForWidth(w))

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(_AA)
        p.setOpacity(self._opacity)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = min(r.height() / 2, 18)
        p.setBrush(qcolor(theme.PILL_BG, 238))
        p.setPen(QtGui.QPen(qcolor(theme.WHITE, 40), 1))
        p.drawRoundedRect(r, rad, rad)
        if self.error:
            p.setPen(_NOPEN)
            p.setBrush(QtGui.QColor(theme.CORAL))
            p.drawEllipse(QtCore.QPointF(18, r.center().y()), 3.5, 3.5)
        p.setFont(self.font())
        p.setPen(QtGui.QColor(theme.INK))
        p.drawText(QtCore.QRectF(self.contentsRect()),
                   int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), self.text())


class ShortcutsPopover(QtWidgets.QWidget):
    """Small dark card listing the keys; click it or press Esc to dismiss."""
    ROWS = [("Space", "Translate the area"), ("Esc", "Clear translations"),
            ("Alt", "Hold to peek at the original"), ("T", "Toggle always on top"),
            ("Click", "Copy a translation")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fk = ui_font(12, QtGui.QFont.Weight.Medium)
        self._ft = ui_font(13)
        self._title = ui_font(12, QtGui.QFont.Weight.Medium)
        mk = QtGui.QFontMetrics(self._fk)
        mt = QtGui.QFontMetrics(self._ft)
        self._kw = max(mk.horizontalAdvance(k) for k, _ in self.ROWS) + 16
        tw = max(mt.horizontalAdvance(t) for _, t in self.ROWS)
        self._row = 28
        self.setFixedSize(16 + self._kw + 12 + tw + 18, 14 + 24 + len(self.ROWS) * self._row + 8)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def popup(self, ms=8000):
        self.show()
        self.raise_()
        self._timer.start(ms)

    def mousePressEvent(self, event):
        self.hide()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(_AA)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(qcolor(theme.PILL_BG, 242))
        p.setPen(QtGui.QPen(qcolor(theme.WHITE, 26), 1))
        p.drawRoundedRect(r, 14, 14)
        p.setFont(self._title)
        p.setPen(qcolor(theme.INK, 150))
        p.drawText(QtCore.QRectF(16, 12, self.width() - 32, 20), int(Qt.AlignmentFlag.AlignVCenter), "Keyboard shortcuts")
        y = 40
        for key, text in self.ROWS:
            chip = QtCore.QRectF(16, y + 3, self._kw, self._row - 6)
            p.setPen(QtGui.QPen(qcolor(theme.WHITE, 36), 1))
            p.setBrush(qcolor(theme.WHITE, 18))
            p.drawRoundedRect(chip.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            p.setFont(self._fk)
            p.setPen(QtGui.QColor(theme.INK))
            p.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), key)
            p.setFont(self._ft)
            p.setPen(qcolor(theme.INK, 220))
            p.drawText(QtCore.QRectF(chip.right() + 12, y, self.width() - chip.right() - 12, self._row),
                       int(Qt.AlignmentFlag.AlignVCenter), text)
            y += self._row


# --------------------------------------------------------------------------- canvas

class TransparentCentralWidget(QtWidgets.QWidget):
    """Whole-window canvas: paints the frame, its glow and the pill shadow; hosts the capture
    area, toolbar, hint, toast and shortcut card; handles frame drag/resize."""

    def __init__(self, overlay_labels, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self._hover = False
        self._breath = 1.0          # 1 = full strength; pulses down while busy
        self._flash = 0.0
        self._toast_msg = ("", False)
        self.toast_in_toolbar_row = False
        self.capture_area = CaptureArea(overlay_labels, self)
        self.hint = HintPill(self)
        self.toolbar = Toolbar(self)
        self.shortcuts = ShortcutsPopover(self)
        self.status_label = Toast(self)
        # One timer: a newer show_status restarts it, so an older call's timeout can never
        # hide a newer message.
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._fade_out_toast)
        self._toast_anim = QtCore.QVariantAnimation(self)
        self._toast_anim.valueChanged.connect(lambda v: self.status_label.set_opacity(v))
        self._toast_anim.finished.connect(self._toast_anim_done)
        self._breath_anim = _anim(self, theme.BREATH_MS)
        self._breath_anim.setLoopCount(-1)
        self._breath_anim.valueChanged.connect(self._on_breath)
        self._flash_anim = _anim(self, theme.FLASH_MS, 1.0, 0.0, QtCore.QEasingCurve.Type.OutCubic)
        self._flash_anim.valueChanged.connect(self._on_flash)
        self._flash_anim.finished.connect(lambda: self._on_flash(0.0))
        self._relayout()

    # geometry ----------------------------------------------------------------
    def capture_rect(self):
        return QtCore.QRect(*geo.capture_rect(self.width(), self.height()))

    def frame_rectf(self):
        return QtCore.QRectF(*geo.frame_rect(self.width(), self.height()))

    def _relayout(self):
        w, h = self.width(), self.height()
        cap = self.capture_rect()
        self.capture_area.setGeometry(cap)
        fx, fy, fw, fh = geo.frame_rect(w, h)
        self.toolbar.move(int(round(fx + (fw - self.toolbar.width()) / 2)), geo.pill_top(h))
        self.hint.move(cap.x() + (cap.width() - self.hint.width()) // 2, cap.y() + (cap.height() - self.hint.height()) // 2)
        self.shortcuts.move(cap.center().x() - self.shortcuts.width() // 2 + 1,
                            cap.center().y() - self.shortcuts.height() // 2 + 1)
        if self.status_label.isVisible():
            self._place_toast()
        self.toolbar.raise_()
        self.status_label.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    # painting ----------------------------------------------------------------
    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(_AA)
        self._paint_pill_shadow(p)
        f = self.frame_rectf()
        rad = theme.FRAME_RADIUS
        k = self._breath
        p.setBrush(_NOBRUSH)
        # soft halo: a faint dark ring for light pages, then widening accent strokes
        for width, col, a in ((10, QtGui.QColor(0, 0, 0), 22), (8, QtGui.QColor(theme.ACCENT), 8),
                              (6, QtGui.QColor(theme.ACCENT), 18), (4, QtGui.QColor(theme.ACCENT), 30)):
            col.setAlpha(int(a * k))
            p.setPen(QtGui.QPen(col, width))
            p.drawRoundedRect(f, rad, rad)
        accent = QtGui.QColor(theme.ACCENT_HOVER if self._hover else theme.ACCENT)
        accent.setAlpha(int(255 * (0.45 + 0.55 * k)))
        p.setPen(QtGui.QPen(accent, theme.FRAME_STROKE))
        p.drawRoundedRect(f, rad, rad)
        p.setPen(QtGui.QPen(qcolor(theme.WHITE, 89), 1))
        p.drawRoundedRect(f.adjusted(1.5, 1.5, -1.5, -1.5), rad - 1.5, rad - 1.5)
        if self._flash > 0:
            steps = 9
            for i in range(steps):
                a = 120 * (1 - i / steps) ** 2 * self._flash
                inset = 2.5 + i * 1.2
                p.setPen(QtGui.QPen(qcolor(theme.WHITE, a), 1.4))
                p.drawRoundedRect(f.adjusted(inset, inset, -inset, -inset), max(2, rad - inset), max(2, rad - inset))

    def _paint_pill_shadow(self, p):
        r = QtCore.QRectF(self.toolbar.geometry())
        clip = QtGui.QPainterPath()
        clip.addRect(QtCore.QRectF(self.rect()))
        hole = QtGui.QPainterPath()
        hole.addRoundedRect(r, theme.PILL_RADIUS, theme.PILL_RADIUS)
        p.save()
        p.setClipPath(clip.subtracted(hole))
        p.setPen(_NOPEN)
        for grow, a in ((5, 6), (4, 9), (3, 13), (2, 18), (1, 22)):
            p.setBrush(QtGui.QColor(0, 0, 0, a))
            p.drawRoundedRect(r.adjusted(-grow, -grow + 2.5, grow, grow + 2.5),
                              theme.PILL_RADIUS + grow, theme.PILL_RADIUS + grow)
        p.restore()

    # animations ----------------------------------------------------------------
    def _on_breath(self, v):
        self._breath = 0.5 + 0.5 * math.cos(2 * math.pi * float(v))
        self.update()

    def set_breathing(self, on):
        if on:
            self._breath_anim.start()
        else:
            self._breath_anim.stop()
            self._breath = 1.0
            self.update()

    def is_breathing(self):
        return self._breath_anim.state() == QtCore.QAbstractAnimation.State.Running

    def _on_flash(self, v):
        self._flash = float(v)
        self.update()

    def flash(self):
        """White inner glow on the frame; call only after the grab."""
        self._flash_anim.stop()
        self._flash = 1.0
        self._flash_anim.start()
        self.update()

    def stop_flash(self):
        self._flash_anim.stop()
        self._flash = 0.0
        self.update()

    def flash_active(self):
        return self._flash > 0

    # toast -------------------------------------------------------------------------
    def _place_toast(self):
        """Toolbar row first: a pill of the same height right of the toolbar pill (else left of
        it); only when neither fits, inside the bottom of the frame."""
        t = self.status_label
        text, error = self._toast_msg
        pill = self.toolbar.geometry()
        nat = t.natural_width(text, error)
        gap = 8
        if pill.right() + 1 + gap + nat <= self.width() - geo.HALO:
            x = pill.right() + 1 + gap
        elif pill.left() - gap - nat >= geo.HALO:
            x = pill.left() - gap - nat
        else:
            x = None
        if x is not None:
            t.set_message(text, error, nat, fixed_h=theme.PILL_H)
            t.move(x, pill.top())
            self.toast_in_toolbar_row = True
            return
        cap = self.capture_rect()
        t.set_message(text, error, max(80, cap.width() - 32))
        t.move(cap.center().x() - t.width() // 2 + 1, cap.bottom() - t.height() - 14)
        self.toast_in_toolbar_row = False

    def show_status(self, text, duration=2000, error=False):
        t = self.status_label
        self._toast_msg = (text, error)
        self._place_toast()
        self._toast_anim.stop()
        fading_in = not t.isVisible()
        if fading_in:
            t.set_opacity(0.0)
        t.show()
        t.raise_()   # overlays are siblings; keep the toast above them
        self._toast_anim.setDuration(theme.TOAST_IN_MS)
        self._toast_anim.setStartValue(t.opacity())
        self._toast_anim.setEndValue(1.0)
        self._toast_anim.start()
        self._status_timer.start(duration)

    def _fade_out_toast(self):
        self._toast_anim.stop()
        self._toast_anim.setDuration(theme.TOAST_OUT_MS)
        self._toast_anim.setStartValue(self.status_label.opacity())
        self._toast_anim.setEndValue(0.0)
        self._toast_anim.start()

    def _toast_anim_done(self):
        if self.status_label.opacity() <= 0.01:
            self.status_label.hide()

    def hide_status(self):
        self._status_timer.stop()
        self._toast_anim.stop()
        self.status_label.hide()

    # frame interaction ----------------------------------------------------------------
    def _hit(self, pos):
        return geo.hit_test(pos.x(), pos.y(), self.width(), self.height())

    def set_hover(self, on):
        if on != self._hover:
            self._hover = on
            self.update()

    def mouseMoveEvent(self, event):
        kind, edges = self._hit(event.position())
        self.set_hover(kind is not None)
        if kind == "resize":
            self.setCursor(_CURSORS.get(edges, Qt.CursorShape.ArrowCursor))
        elif kind == "move":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.unsetCursor()

    def leaveEvent(self, event):
        self.set_hover(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        kind, edges = self._hit(event.position())
        win = self.window()
        if kind == "resize":
            win.start_resize(edges)
        elif kind == "move":
            win.start_move()



class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Instant Translator (Performance Edition)")
        self.setWindowIcon(icons.make_app_icon())
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(theme.MENU_QSS)

        self.overlay_labels = []
        self.central = TransparentCentralWidget(self.overlay_labels, self)
        self.capture_area = self.central.capture_area
        self.toolbar = self.central.toolbar
        self.setCentralWidget(self.central)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.central.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(*geo.MIN_WINDOW)
        self.resize(820, 668)
        if CONFIG.on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self.worker = None
        self.busy = False
        self._capture_pending = False
        self._error_shown = False
        self._build_menus()
        self._wire_toolbar()
        self.refresh_toolbar()
        self.central.hint.show_now()

    # toolbar ----------------------------------------------------------------------
    def _wire_toolbar(self):
        tb = self.toolbar
        tb.grip.pressed.connect(self.start_move)
        tb.chip.clicked.connect(self._popup_lang_menu)
        tb.translate_btn.clicked.connect(self.capture_transparent_area)
        tb.clear_btn.clicked.connect(self.clear_with_toast)
        tb.pin_btn.clicked.connect(self.toggle_always_on_top)
        tb.more_btn.clicked.connect(self._popup_more_menu)
        tb.close_btn.clicked.connect(lambda: self.close())

    def _build_menus(self):
        self.lang_menu = make_menu(self)
        self.lang_actions = {}
        for code, text in (("auto", "Detect automatically"), ("de", "German")):
            act = self.lang_menu.addAction(text)
            act.triggered.connect(lambda _=False, c=code: self.set_source_lang(c))
            self.lang_actions[code] = act
        self.more_menu = make_menu(self)
        self.shortcuts_action = self.more_menu.addAction("Keyboard shortcuts")
        self.shortcuts_action.triggered.connect(self.show_shortcuts)
        self.more_menu.addSeparator()
        self.quit_action = self.more_menu.addAction("Quit")
        self.quit_action.triggered.connect(lambda: self.close())

    def _popup_menu(self, menu, button):
        menu.ensurePolished()
        size = menu.sizeHint()
        pos = button.mapToGlobal(QtCore.QPoint((button.width() - size.width()) // 2, -size.height() - 10))
        menu.popup(pos)

    def _popup_lang_menu(self):
        self.refresh_toolbar()
        self._popup_menu(self.lang_menu, self.toolbar.chip)

    def _popup_more_menu(self):
        self._popup_menu(self.more_menu, self.toolbar.more_btn)

    def lang_label(self):
        src = "Auto" if CONFIG.source_lang == "auto" else CONFIG.source_lang.upper()
        return f"{src} → {CONFIG.target_lang.upper()}"

    def refresh_toolbar(self):
        self.toolbar.chip.setText(self.lang_label())
        self.toolbar.refit()
        self.central._relayout()
        on = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.toolbar.pin_btn.set_toggled(on)
        for code, act in self.lang_actions.items():
            act.setIcon(icons.make_icon("check", theme.INK) if code == CONFIG.source_lang else icons.blank_icon())

    def set_source_lang(self, code):
        """Switch the source language; cached translations belong to the old one."""
        CONFIG.source_lang = code
        translate.clear_translation_cache()
        worker_mod.clear_capture_cache()
        self.clearOverlays()
        self.refresh_toolbar()
        self.central.show_status(f"Source: {'auto-detect' if code == 'auto' else self.lang_actions[code].text()}", 1500)

    def show_shortcuts(self):
        self.central.hint.hide_now()
        self.central.shortcuts.popup()

    def start_move(self):
        h = self.windowHandle()
        return bool(h and h.startSystemMove())

    def start_resize(self, edges):
        h = self.windowHandle()
        return bool(h and h.startSystemResize(edges_to_qt(edges)))

    # geometry ---------------------------------------------------------------------
    def get_transparent_area_geometry(self):
        """Global (x, y, w, h) of the capture area: strictly inside the frame, never the toolbar."""
        geom = self.central.capture_rect()
        global_top_left = self.central.mapToGlobal(geom.topLeft())
        return global_top_left.x(), global_top_left.y(), geom.width(), geom.height()

    def get_capture_geometry(self):
        """Return (screen, x, y, w, h) with x, y relative to the screen the window is on."""
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        gx, gy, w, h = self.get_transparent_area_geometry()
        origin = screen.geometry().topLeft()
        return screen, gx - origin.x(), gy - origin.y(), w, h

    # state ------------------------------------------------------------------------
    def set_busy(self, busy):
        self.busy = bool(busy)
        self.toolbar.translate_btn.set_busy(self.busy)
        self.central.set_breathing(self.busy)
        self.update_hint()

    def update_hint(self, immediate=False):
        want = not self.overlay_labels and not self.busy and not self.central.shortcuts.isVisible()
        hint = self.central.hint
        if want:
            hint.fade_to(1.0)
        elif immediate:
            hint.hide_now()
        else:
            hint.fade_to(0.0)

    def clearOverlays(self):
        for label in self.overlay_labels:
            label.hide()
            label.deleteLater()
        self.overlay_labels.clear()
        self.capture_area.update()

    def clear_with_toast(self):
        self.clearOverlays()
        self.central.shortcuts.hide()
        self.central.show_status("Overlays cleared", 1000)
        self.update_hint()

    def hide_capture_ui(self):
        """Everything of ours that can sit inside the capture rect must be gone before a grab."""
        self.clearOverlays()
        self.central.hide_status()
        self.central.shortcuts.hide()
        self.central.hint.hide_now()
        self.central.stop_flash()

    def capture_transparent_area(self):
        """Prepare a capture: hide our own UI, then grab after the compositor repaints."""
        if (self.worker is not None and self.worker.isRunning()) or self._capture_pending:
            return

        self._capture_pending = True
        self.set_busy(True)
        self.hide_capture_ui()
        QtWidgets.QApplication.processEvents()
        QtCore.QTimer.singleShot(CONFIG.capture_delay_ms, self._do_grab)

    def _do_grab(self):
        self._capture_pending = False
        self._error_shown = False
        self.hide_capture_ui()   # belt and braces: nothing may have reappeared during the delay
        screen, x, y, w, h = self.get_capture_geometry()
        screenshot = screen.grabWindow(0, x, y, w, h)
        qimage = screenshot.toImage()
        img_bgr = qimage_to_bgr(qimage)

        self.central.flash()   # only now: the glow must never be in the capture
        self.central.show_status("OCR + translating…", 3000)

        self.worker = TranslationWorker(img_bgr, dpr=screen.devicePixelRatio())
        self.worker.finished_translation.connect(self.on_translation_finished)
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    @QtCore.pyqtSlot(str)
    def on_worker_error(self, message):
        self._error_shown = True
        self.set_busy(False)
        if message.endswith(".") and not message.endswith(".."):
            message = message[:-1]
        self.central.show_status(message, 5000, error=True)

    @QtCore.pyqtSlot(list)
    def on_translation_finished(self, result_data):
        self.set_busy(False)

        if not result_data:
            if self._error_shown:
                return   # keep the specific error message visible
            self.central.show_status("No text found or translation failed", 2000)
            return

        if not self._error_shown:   # keep a translation error visible over the success toast
            self.central.show_status(f"Translated {len(result_data)} paragraphs", 1500)

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

            label = OverlayLabel(self.capture_area)
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
            label.setAlignment((Qt.AlignmentFlag.AlignVCenter if single else Qt.AlignmentFlag.AlignTop)
                               | Qt.AlignmentFlag.AlignLeft)
            bg = tuple(item.get('bg') or render.DEFAULT_BG)
            fg = render.pick_text_color(bg)
            label.setStyleSheet(f"""
                QLabel {{
                    background-color: rgb({bg[0]}, {bg[1]}, {bg[2]});
                    color: rgb({fg[0]}, {fg[1]}, {fg[2]});
                    padding: {render.PAD}px {render.PAD + 1}px;
                    border-radius: {theme.OVERLAY_RADIUS}px;
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
        self.capture_area.update()
        self.update_hint()
        # keep the toast above everything created after it
        self.central.status_label.raise_()

    def copy_overlay_text(self, label):
        QtWidgets.QApplication.clipboard().setText(label.plain_text)
        label.flash_ring()
        self.central.show_status("Copied", 1000)

    def _worker_finished(self):
        if self.worker is not None:
            self.worker.deleteLater()
            QtCore.QTimer.singleShot(0, self._clear_worker)

    def _clear_worker(self):
        self.worker = None

    def toggle_always_on_top(self):
        """Flip WindowStaysOnTopHint; Qt hides the window on a flag change, so re-show it in place."""
        on = not bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        was_visible = self.isVisible()
        geom = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)   # leaves the frameless flag alone
        if was_visible:
            self.show()
        self.setGeometry(geom)
        self.refresh_toolbar()
        self.central.show_status(f"Always on top: {'on' if on else 'off'}", 1500)

    def showEvent(self, event):
        super().showEvent(event)
        self.central.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.capture_transparent_area()
        elif event.key() == Qt.Key.Key_Escape:
            self.clear_with_toast()
        elif event.key() == Qt.Key.Key_T:
            self.toggle_always_on_top()
        elif event.key() == Qt.Key.Key_Alt:
            for label in self.overlay_labels:
                label.hide()
            self.capture_area.update()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Alt:
            for label in self.overlay_labels:
                label.show()
            self.capture_area.update()
        else:
            super().keyReleaseEvent(event)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()   # destroying a running QThread aborts the process; OCR cannot be cut short
        event.accept()
