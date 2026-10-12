"""Render every UI state of the floating-frame window over a sample page into PNGs
(offscreen cannot composite a real desktop, so the page is painted behind the window here).

    QT_QPA_PLATFORM=offscreen uv run python scripts/render_ui_states.py OUT_DIR [state ...]

Writes OUT_DIR/<state>_<light|dark>_<1x|2x>.png (+ _toolbar crops at 2x). Needs the OCR
models for the `translated` states (same as the test-suite)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from pytranslate import geometry as geo  # noqa: E402
from pytranslate.capture import bgr_to_qimage  # noqa: E402
from pytranslate.config import CONFIG  # noqa: E402
from pytranslate.ui import MainWindow  # noqa: E402
from tests import helpers  # noqa: E402

STATES = ["idle", "idle_frame_hover", "busy", "flash", "translated", "overlay_hover", "toast_copied",
          "toast_error", "pinned", "menu_language", "menu_more", "shortcuts"]


def page_background(dark):
    bgr, _ = helpers.render_web_page()
    img = bgr_to_qimage(bgr).convertToFormat(QtGui.QImage.Format.Format_RGB32)
    if dark:
        img.invertPixels()
        p = QtGui.QPainter(img)
        p.fillRect(img.rect(), QtGui.QColor(20, 20, 30, 60))
        p.end()
    return img, bgr


def settle(win):
    """Jump every running animation to its end so the frame is deterministic."""
    c = win.central
    if c.status_label.isVisible():
        c._toast_anim.stop()
        c.status_label.set_opacity(1.0)
        c._status_timer.stop()
    if win.overlay_labels or win.busy or c.shortcuts.isVisible():
        c.hint.hide_now()
    elif c.hint.isVisible():
        c.hint.show_now()
    for lb in win.overlay_labels:
        a = getattr(lb, "anim_ref", None)
        try:
            if a is not None:
                a.stop()
        except RuntimeError:
            pass
        lb.setGraphicsEffect(None)   # QWidget.render() offsets widgets that have an effect
    c.stop_flash() if not getattr(win, "_keep_flash", False) else None


def build(state, result, dark):
    CONFIG.on_top = False
    win = MainWindow()
    page_w, page_h = helpers.PAGE_SIZE
    win.resize(page_w + 2 * (geo.HALO + geo.CAPTURE_INSET), page_h + 2 * geo.CAPTURE_INSET + geo.HALO + geo.TOOLBAR_H)
    win.show()
    QtWidgets.QApplication.processEvents()
    c = win.central
    menu = None
    if state == "idle_frame_hover":
        c._hover = True
    elif state == "busy":
        win.set_busy(True)
        btn = win.toolbar.translate_btn
        btn._spin.stop()
        btn._set_angle(70)
        c._breath_anim.stop()
        c._on_breath(0.3)
    elif state == "flash":
        c._flash_anim.stop()
        c._on_flash(0.8)
        win._keep_flash = True
    elif state in ("translated", "overlay_hover", "toast_copied", "toast_error"):
        win.on_translation_finished(result)
        QtWidgets.QApplication.processEvents()
        settle(win)
        label = win.overlay_labels[1]
        if state == "overlay_hover":
            label._hover = True
        elif state == "toast_copied":
            win.copy_overlay_text(label)
            label._ring_anim.stop()
            label._set_ring(0.9)
        elif state == "toast_error":
            c.show_status("Translation model not installed: run ./scripts/setup_models.sh", 5000, error=True)
    elif state == "pinned":
        win.toolbar.pin_btn.set_toggled(True)
        win.toolbar.pin_btn._hover = True
    elif state == "menu_language":
        win.refresh_toolbar()
        win._popup_lang_menu()
        menu = win.lang_menu
    elif state == "menu_more":
        win._popup_more_menu()
        menu = win.more_menu
    elif state == "shortcuts":
        win.show_shortcuts()
    if state not in ("translated", "overlay_hover", "toast_copied", "toast_error"):
        QtWidgets.QApplication.processEvents()
    settle(win)
    return win, menu


def render(win, menu, dark, dpr):
    bg, _ = page_background(dark)
    w, h = win.width(), win.height()
    cap = win.central.capture_rect()
    canvas = QtGui.QImage(int(w * dpr), int(h * dpr), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    canvas.setDevicePixelRatio(dpr)
    # the "screen" behind the window: page pixels extended to the edges
    base = QtGui.QImage(canvas.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    base.setDevicePixelRatio(dpr)
    base.fill(bg.pixelColor(0, 0))
    bp = QtGui.QPainter(base)
    bp.drawImage(cap.x(), cap.y(), bg)
    bp.end()
    layer = QtGui.QImage(canvas.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    layer.setDevicePixelRatio(dpr)
    layer.fill(QtCore.Qt.GlobalColor.transparent)
    lp = QtGui.QPainter(layer)
    win.render(lp)
    if menu is not None and menu.isVisible():
        top_left = menu.geometry().topLeft() - win.geometry().topLeft()
        lp.drawPixmap(top_left, menu.grab())
    lp.end()
    p = QtGui.QPainter(base)
    p.drawImage(0, 0, layer)
    p.end()
    return base


def main(out_dir, states):
    os.makedirs(out_dir, exist_ok=True)
    bgr, _ = helpers.render_web_page()
    result = helpers.run_page_pipeline(bgr)
    written = []
    for state in states:
        for dark in (False, True):
            for dpr in (1.0, 2.0):
                win, menu = build(state, result, dark)
                img = render(win, menu, dark, dpr)
                name = f"{state}_{'dark' if dark else 'light'}_{int(dpr)}x"
                path = os.path.join(out_dir, name + ".png")
                img.save(path)
                written.append(path)
                if dpr == 2.0:
                    ratio = int(dpr)
                    w, h = win.width(), win.height()
                    crop = img.copy(0, int((h - 130) * ratio), int(w * ratio), int(130 * ratio))
                    # focus on the pill: centre 760 px
                    crop = crop.copy(int((w - 760) / 2 * ratio), 0, int(760 * ratio), crop.height())
                    crop.save(os.path.join(out_dir, name + "_toolbar.png"))
                if menu is not None:
                    menu.hide()
                win.close()
                win.deleteLater()
                QtWidgets.QApplication.processEvents()
    print("\n".join(written))


if __name__ == "__main__":
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    out = sys.argv[1] if len(sys.argv) > 1 else "ui_states"
    main(out, sys.argv[2:] or STATES)
