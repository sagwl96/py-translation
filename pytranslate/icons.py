"""Toolbar icons (inline Tabler-style outline SVGs) and the app icon, all drawn in code."""
from PyQt6 import QtCore, QtGui, QtSvg

from . import theme

_PATHS = {
    "language": ('<path d="M4 5h7"/><path d="M9 3v2c0 4.418 -2.239 8 -5 8"/>'
                 '<path d="M5 9c-.003 2.144 2.952 3.908 6.7 4"/>'
                 '<path d="M12 20l4 -9l4 9"/><path d="M19.1 18h-6.2"/>'),
    "eraser": ('<path d="M20 20h-10.5l-4.21 -4.3a1 1 0 0 1 0 -1.41l10 -10a1 1 0 0 1 1.41 0l5 5'
               'a1 1 0 0 1 0 1.41l-9.2 9.3"/><path d="M18 13.3l-6.3 -6.3"/>'),
    "pin": ('<path d="M15 4.5l-4 4l-4 1.5l-1.5 1.5l7 7l1.5 -1.5l1.5 -4l4 -4"/>'
            '<path d="M9 15l-4.5 4.5"/><path d="M14.5 4l5.5 5.5"/>'),
    "dots": ('<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/>'
             '<circle cx="19" cy="12" r="1"/>'),
    "x": '<path d="M18 6l-12 12"/><path d="M6 6l12 12"/>',
    "check": '<path d="M5 12l5 5l10 -10"/>',
    "chevron": '<path d="M6 9l6 6l6 -6"/>',
}
_renderers = {}


def _renderer(name, color):
    key = (name, color)
    if key not in _renderers:
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               f'stroke="{color}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
               f'{_PATHS[name]}</svg>')
        _renderers[key] = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode()))
    return _renderers[key]


def draw_icon(painter, name, rect, color=theme.INK):
    """Draw the named icon into rect (QRectF) with the painter's current transform."""
    _renderer(name, color).render(painter, rect)


def make_icon(name, color=theme.INK, size=16):
    """A QIcon (used for menu items)."""
    pm = QtGui.QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    draw_icon(p, name, QtCore.QRectF(0, 0, size, size), color)
    p.end()
    return QtGui.QIcon(pm)


def blank_icon(size=16):
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    return QtGui.QIcon(pm)


def paint_app_icon(p, size):
    """The app icon into a size x size square: accent tile, white frame brackets, a speech
    bubble with an arrow."""
    s = float(size)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(theme.ACCENT_DEEP))
    p.drawRoundedRect(QtCore.QRectF(0, 0, s, s), s * 0.22, s * 0.22)
    white = QtGui.QColor("white")
    # corner brackets
    pen = QtGui.QPen(white, max(1.0, s * 0.07))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    a, b, ln = s * 0.17, s * 0.83, s * 0.2
    for (cx, cy, dx, dy) in ((a, a, 1, 1), (b, a, -1, 1), (a, b, 1, -1), (b, b, -1, -1)):
        path = QtGui.QPainterPath(QtCore.QPointF(cx + dx * ln, cy))
        path.lineTo(cx, cy)
        path.lineTo(cx, cy + dy * ln)
        p.drawPath(path)
    # speech bubble
    bub = QtCore.QRectF(s * 0.3, s * 0.34, s * 0.4, s * 0.27)
    path = QtGui.QPainterPath()
    path.addRoundedRect(bub, s * 0.07, s * 0.07)
    tail = QtGui.QPainterPath(QtCore.QPointF(s * 0.38, bub.bottom() - s * 0.01))
    tail.lineTo(s * 0.37, s * 0.72)
    tail.lineTo(s * 0.5, bub.bottom() - s * 0.01)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(white)
    p.drawPath(path.united(tail))
    # arrow inside the bubble
    pen = QtGui.QPen(QtGui.QColor(theme.ACCENT_DEEP), max(1.0, s * 0.05))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    cy = bub.center().y()
    x0, x1 = s * 0.38, s * 0.62
    p.drawLine(QtCore.QPointF(x0, cy), QtCore.QPointF(x1, cy))
    p.drawLine(QtCore.QPointF(x1 - s * 0.06, cy - s * 0.06), QtCore.QPointF(x1, cy))
    p.drawLine(QtCore.QPointF(x1 - s * 0.06, cy + s * 0.06), QtCore.QPointF(x1, cy))


def make_app_icon():
    icon = QtGui.QIcon()
    for size in (16, 32, 64, 128, 256):
        pm = QtGui.QPixmap(size, size)
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        paint_app_icon(p, size)
        p.end()
        icon.addPixmap(pm)
    return icon
