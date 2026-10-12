from PyQt6 import QtCore, QtTest, QtWidgets

from pytranslate.config import CONFIG
from pytranslate.ui import MainWindow

ON_TOP = QtCore.Qt.WindowType.WindowStaysOnTopHint


def test_t_key_toggles_always_on_top(qapp):
    win = MainWindow()
    win.show()
    win.setGeometry(50, 60, 500, 400)
    geom = win.geometry()
    assert not win.windowFlags() & ON_TOP

    QtTest.QTest.keyClick(win, QtCore.Qt.Key.Key_T)
    assert win.windowFlags() & ON_TOP
    assert win.isVisible()
    assert win.central.status_label.text() == "Always on top: on"
    assert win.geometry().size() == geom.size()

    QtTest.QTest.keyClick(win, QtCore.Qt.Key.Key_T)
    assert not win.windowFlags() & ON_TOP
    assert win.central.status_label.text() == "Always on top: off"
    win.close()


def test_on_top_config_starts_enabled(qapp, monkeypatch):
    monkeypatch.setattr(CONFIG, "on_top", True)
    win = MainWindow()
    assert win.windowFlags() & ON_TOP


def _result(text):
    return {"text": text, "par_rect": (10, 10, 200, 40), "line_rects": [(10, 10, 200, 20)]}


def test_click_overlay_copies_plain_text(qapp):
    win = MainWindow()
    win.resize(400, 300)
    win.show()
    win.on_translation_finished([_result("Fish & <chips>"), _result("second")])
    first = win.overlay_labels[0]
    assert first.toolTip() == "Click to copy"
    assert first.cursor().shape() == QtCore.Qt.CursorShape.PointingHandCursor

    QtTest.QTest.mouseClick(first, QtCore.Qt.MouseButton.LeftButton)
    assert QtWidgets.QApplication.clipboard().text() == "Fish & <chips>"
    assert win.central.status_label.text() == "Copied"

    QtTest.QTest.mouseClick(win.overlay_labels[1], QtCore.Qt.MouseButton.LeftButton)
    assert QtWidgets.QApplication.clipboard().text() == "second"
    win.close()


def test_right_click_and_transparent_area_do_not_copy(qapp):
    win = MainWindow()
    win.resize(400, 300)
    win.show()
    win.on_translation_finished([_result("hello")])
    QtWidgets.QApplication.clipboard().setText("untouched")
    win.central.show_status("other", 1000)

    QtTest.QTest.mouseClick(win.overlay_labels[0], QtCore.Qt.MouseButton.RightButton)
    QtTest.QTest.mouseClick(win.central, QtCore.Qt.MouseButton.LeftButton,
                            pos=QtCore.QPoint(350, 250))
    assert QtWidgets.QApplication.clipboard().text() == "untouched"
    assert win.central.status_label.text() != "Copied"
    win.close()


def test_overlay_and_toast_show_quotes_literally(qapp):
    # Regression: html-escaped text in an auto-format QLabel rendered as "&quot;"
    win = MainWindow()
    text = 'He said "stop" & it\'s <fine>'
    win.on_translation_finished([_result(text)])
    label = win.overlay_labels[0]
    assert label.textFormat() == QtCore.Qt.TextFormat.PlainText
    assert label.text() == text
    win.central.show_status('Error: "x" <y>', 1000)
    assert win.central.status_label.textFormat() == QtCore.Qt.TextFormat.PlainText
    assert win.central.status_label.text() == 'Error: "x" <y>'
    win.close()


def test_toast_stays_above_overlays(qapp):
    # Regression: overlays (created later, same parent) covered the "Copied" toast
    win = MainWindow()
    win.on_translation_finished([_result("first"), _result("second")])
    assert win.central.children()[-1] is win.central.status_label
    win.copy_overlay_text(win.overlay_labels[0])
    assert win.central.children()[-1] is win.central.status_label
    assert win.central.status_label.text() == "Copied"
    win.close()
