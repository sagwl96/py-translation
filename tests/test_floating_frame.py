"""Floating-frame UI: geometry, hit-testing, toolbar actions, grab safety, icon."""
from PyQt6 import QtCore, QtGui, QtTest

from pytranslate import geometry as geo
from pytranslate import translate, ui, worker as worker_mod
from pytranslate.config import CONFIG
from pytranslate.icons import make_app_icon

Qt = QtCore.Qt


def _win(qapp, w=600, h=480):
    win = ui.MainWindow()
    win.resize(w, h)
    win.show()
    qapp.processEvents()
    return win


def test_capture_rect_inside_frame_and_clear_of_toolbar(qapp):
    win = _win(qapp)
    W, H = win.width(), win.height()
    cx, cy, cw, ch = geo.capture_rect(W, H)
    fx, fy, fw, fh = geo.frame_rect(W, H)
    assert cx - fx >= 4 and cy - fy >= 4 and (fx + fw) - (cx + cw) >= 4 and (fy + fh) - (cy + ch) >= 4
    tb = win.toolbar.geometry()
    assert cy + ch < tb.top()          # toolbar zone is below the capture rect
    assert 0 <= cx and cx + cw <= W and cy + ch <= H
    gx, gy, w, h = win.get_transparent_area_geometry()
    top_left = win.central.mapToGlobal(QtCore.QPoint(cx, cy))
    assert (gx, gy, w, h) == (top_left.x(), top_left.y(), cw, ch)
    win.close()


def test_hit_test_edges_and_move():
    W, H = 600, 480
    fx, fy, fw, fh = geo.frame_rect(W, H)
    mid_x, mid_y = fx + fw // 2, fy + fh // 2
    assert geo.hit_test(mid_x, mid_y, W, H)[0] is None                       # capture area
    assert geo.hit_test(mid_x, fy, W, H) == ("move", frozenset())            # on the stroke
    assert geo.hit_test(mid_x, fy + 4, W, H) == ("move", frozenset())        # inner band
    assert geo.hit_test(mid_x, fy - 4, W, H) == ("resize", frozenset("t"))
    assert geo.hit_test(fx - 4, mid_y, W, H) == ("resize", frozenset("l"))
    assert geo.hit_test(fx + fw + 4, mid_y, W, H) == ("resize", frozenset("r"))
    assert geo.hit_test(mid_x, fy + fh + 4, W, H) == ("resize", frozenset("b"))
    assert geo.hit_test(fx - 4, fy - 4, W, H) == ("resize", frozenset("lt"))
    assert geo.hit_test(fx + fw + 4, fy + fh + 4, W, H) == ("resize", frozenset("rb"))
    assert geo.hit_test(fx + 6, fy - 4, W, H) == ("resize", frozenset("lt"))   # corner extent along an edge
    assert geo.hit_test(0, 0, W, H)[0] is None                               # far outside
    assert geo.hit_test(mid_x, H - 20, W, H)[0] is None                      # toolbar zone


def test_ring_press_starts_move_and_resize(qapp, monkeypatch):
    win = _win(qapp)
    calls = []
    monkeypatch.setattr(win, "start_move", lambda: calls.append("move"))
    monkeypatch.setattr(win, "start_resize", lambda e: calls.append(("resize", e)))
    W, H = win.width(), win.height()
    fx, fy, fw, fh = geo.frame_rect(W, H)
    QtTest.QTest.mouseClick(win.central, Qt.MouseButton.LeftButton, pos=QtCore.QPoint(fx + fw // 2, fy))
    QtTest.QTest.mouseClick(win.central, Qt.MouseButton.LeftButton, pos=QtCore.QPoint(fx - 4, fy + fh // 2))
    QtTest.QTest.mouseClick(win.central, Qt.MouseButton.LeftButton, pos=QtCore.QPoint(fx + fw // 2, fy + fh // 2))
    assert calls == ["move", ("resize", frozenset("l"))]
    win.close()


def test_frameless_and_translucent_survive_always_on_top_toggle(qapp):
    win = _win(qapp)
    frameless = Qt.WindowType.FramelessWindowHint
    ontop = Qt.WindowType.WindowStaysOnTopHint
    assert win.windowFlags() & frameless
    assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    win.toggle_always_on_top()
    assert win.windowFlags() & frameless and win.windowFlags() & ontop
    assert win.toolbar.pin_btn.toggled_on
    win.toggle_always_on_top()
    assert win.windowFlags() & frameless and not win.windowFlags() & ontop
    assert not win.toolbar.pin_btn.toggled_on
    win.close()


def test_minimum_size(qapp):
    win = _win(qapp)
    assert win.minimumSize() == QtCore.QSize(*geo.MIN_WINDOW)
    cap_w = geo.MIN_WINDOW[0] - 2 * (geo.HALO + geo.CAPTURE_INSET)
    assert cap_w >= 240
    assert win.toolbar.width() <= geo.MIN_WINDOW[0] - 2 * geo.HALO   # the pill fits at minimum width
    win.close()


def test_toolbar_buttons(qapp, monkeypatch):
    win = _win(qapp)
    tb = win.toolbar
    hits = []
    monkeypatch.setattr(win, "_do_grab", lambda: hits.append("grab"))
    tb.translate_btn.click()
    assert win.busy and tb.translate_btn.is_busy() and win.central.is_breathing()
    tb.translate_btn.click()          # non-reentrant while pending
    deadline = QtCore.QDeadlineTimer(1000)
    while not hits and not deadline.hasExpired():
        qapp.processEvents()
    assert hits == ["grab"]
    win.set_busy(False)
    assert not tb.translate_btn.is_busy() and not win.central.is_breathing()

    win.on_translation_finished([{"text": "x", "par_rect": (10, 10, 100, 30), "line_rects": [(10, 10, 100, 30)]}])
    assert len(win.overlay_labels) == 1
    tb.clear_btn.click()
    assert win.overlay_labels == []

    tb.pin_btn.click()
    assert win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint and tb.pin_btn.toggled_on
    tb.pin_btn.click()

    closed = []
    monkeypatch.setattr(win, "close", lambda: closed.append(1))
    tb.close_btn.click()
    assert closed == [1]


def test_language_menu_updates_config_and_clears_caches(qapp, monkeypatch):
    monkeypatch.setattr(CONFIG, "source_lang", "auto")
    win = _win(qapp)
    assert win.toolbar.chip.text() == "Auto → EN"
    assert [a.text() for a in win.lang_menu.actions()] == ["Detect automatically", "German"]
    cleared = []
    monkeypatch.setattr(translate, "clear_translation_cache", lambda: cleared.append("t"))
    monkeypatch.setattr(worker_mod, "clear_capture_cache", lambda: cleared.append("c"))
    win.lang_actions["de"].trigger()
    assert CONFIG.source_lang == "de" and win.toolbar.chip.text() == "DE → EN"
    assert cleared == ["t", "c"]
    win.lang_actions["auto"].trigger()
    assert CONFIG.source_lang == "auto" and win.toolbar.chip.text() == "Auto → EN"
    win.close()


def test_more_menu_has_shortcuts_and_quit(qapp):
    win = _win(qapp)
    assert [a.text() for a in win.more_menu.actions() if not a.isSeparator()] == ["Keyboard shortcuts", "Quit"]
    win.shortcuts_action.trigger()
    assert win.central.shortcuts.isVisible()
    QtTest.QTest.keyClick(win, Qt.Key.Key_Escape)
    assert not win.central.shortcuts.isVisible()
    win.close()


class _Screen:
    def __init__(self, seen):
        self.seen = seen

    def devicePixelRatio(self):
        return 1.0

    def grabWindow(self, wid, x, y, w, h):
        win, c = self.seen["win"], self.seen["win"].central
        self.seen["visible"] = {
            "overlays": [lb for lb in win.overlay_labels if lb.isVisible()],
            "hint": c.hint.isVisible(), "toast": c.status_label.isVisible(),
            "shortcuts": c.shortcuts.isVisible(), "flash": c.flash_active()}
        pm = QtGui.QPixmap(w, h)
        pm.fill(QtGui.QColor(255, 255, 255))
        return pm


def test_nothing_of_ours_visible_inside_capture_rect_at_grab(qapp, monkeypatch):
    seen = {}
    win = _win(qapp)
    seen["win"] = win
    win.on_translation_finished([{"text": "x", "par_rect": (10, 10, 100, 30), "line_rects": [(10, 10, 100, 30)]}])
    win.central.shortcuts.popup()
    win.central.flash()
    win.central.show_status("toast", 5000)
    win.central.hint.show_now()
    monkeypatch.setattr(win, "get_capture_geometry", lambda: (_Screen(seen), 0, 0, 20, 20))
    monkeypatch.setattr(worker_mod.TranslationWorker, "start", lambda self: None)
    win.capture_transparent_area()
    deadline = QtCore.QDeadlineTimer(2000)
    while "visible" not in seen and not deadline.hasExpired():
        qapp.processEvents()
    assert seen["visible"] == {"overlays": [], "hint": False, "toast": False, "shortcuts": False, "flash": False}
    assert win.central.flash_active()      # the flash starts only after the grab
    win.worker = None
    win.close()


def test_hint_visibility_follows_state(qapp):
    win = _win(qapp)
    hint = win.central.hint
    assert hint.isVisible()
    win.on_translation_finished([{"text": "x", "par_rect": (10, 10, 100, 30), "line_rects": [(10, 10, 100, 30)]}])
    deadline = QtCore.QDeadlineTimer(600)
    while hint.isVisible() and not deadline.hasExpired():
        qapp.processEvents()
    assert not hint.isVisible()
    QtTest.QTest.keyClick(win, Qt.Key.Key_Escape)
    assert hint.isVisible()
    win.close()


def test_error_toast_has_dot_and_copy_flashes_ring(qapp):
    win = _win(qapp)
    win.on_worker_error("boom")
    assert win.central.status_label.error and win.central.status_label.text() == "boom"
    win.on_translation_finished([{"text": "x", "par_rect": (10, 10, 100, 30), "line_rects": [(10, 10, 100, 30)]}])
    win.copy_overlay_text(win.overlay_labels[0])
    assert win.overlay_labels[0]._ring > 0
    assert not win.central.status_label.error
    win.close()


def test_app_icon_pixmaps(qapp):
    icon = make_app_icon()
    assert not icon.isNull()
    sizes = {s.width() for s in icon.availableSizes()}
    assert {16, 32, 64, 128, 256} <= sizes
    pm = icon.pixmap(64)
    assert not pm.isNull() and pm.toImage().pixelColor(32, 2).alpha() == 255   # tile fills the top edge
    assert MainWindowIconSet.check(qapp)


class MainWindowIconSet:
    @staticmethod
    def check(qapp):
        win = ui.MainWindow()
        ok = not win.windowIcon().isNull()
        win.close()
        return ok


def test_toast_sits_in_toolbar_row_right_of_pill(qapp):
    win = _win(qapp, 820, 668)
    win.central.show_status("Translated 19 paragraphs", 5000)
    t, pill = win.central.status_label, win.toolbar.geometry()
    assert win.central.toast_in_toolbar_row
    assert t.height() == pill.height() == 36 and t.y() == pill.y()
    assert t.x() - (pill.right() + 1) == 8
    assert t.y() > win.central.capture_rect().bottom()        # never over the capture area
    win.close()


def test_toast_falls_back_inside_frame_when_row_is_full(qapp):
    win = _win(qapp, geo.MIN_WINDOW[0], 300)
    win.central.show_status("Translation model not installed: run ./scripts/setup_models.sh", 5000, error=True)
    assert not win.central.toast_in_toolbar_row
    assert win.central.capture_rect().contains(win.central.status_label.geometry())
    win.close()


def test_system_copy_has_no_terminal_period(qapp):
    win = _win(qapp)
    win.on_translation_finished([])
    assert win.central.status_label.text() == "No text found or translation failed"
    win.on_worker_error("Tesseract is missing.")
    assert win.central.status_label.text() == "Tesseract is missing"
    win.clear_with_toast()
    assert win.central.status_label.text() == "Overlays cleared"
    win.close()
