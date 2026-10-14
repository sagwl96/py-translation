"""Render the README GIFs: the real window (offscreen) over the made-up library page of the
tests, with real OCR and the real offline model, frame by frame, stitched with ffmpeg.

    QT_QPA_PLATFORM=offscreen uv run python scripts/render_gifs.py [OUT_DIR]   # default docs/

Writes OUT_DIR/{translate,interact,toolbar}.gif. Needs the models and ffmpeg."""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

import render_ui_states as rs  # noqa: E402
from pytranslate import worker as worker_mod  # noqa: E402

CAPTION_H = 44
WIDTH = 880   # GIF width (px)


def translate_page(bgr):
    """Real pipeline: Tesseract + the installed Argos model."""
    worker_mod.clear_capture_cache()
    out, errors = [], []
    w = worker_mod.TranslationWorker(bgr)
    w.finished_translation.connect(out.append)
    w.error.connect(errors.append)
    w.run()
    if errors or not out or not out[0]:
        sys.exit(f"translation failed: {errors} (run ./scripts/setup_models.sh)")
    return out[0]


def pos_of(win, widget, fx=0.5, fy=0.5):
    """Window coordinates of a point inside `widget` (fractions of its size)."""
    return widget.mapTo(win, QtCore.QPoint(int(widget.width() * fx), int(widget.height() * fy)))


def draw_cursor(p, pt):
    path = QtGui.QPainterPath(QtCore.QPointF(0, 0))
    for x, y in ((0, 17), (4.5, 13), (7.5, 20), (10, 19), (7, 12), (12.5, 12)):
        path.lineTo(x, y)
    path.closeSubpath()
    p.save()
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.translate(pt.x(), pt.y())
    p.setPen(QtGui.QPen(QtGui.QColor("white"), 1.4))
    p.setBrush(QtGui.QColor("black"))
    p.drawPath(path)
    p.restore()


class Film:
    """Collects (frame, seconds) pairs and writes a GIF."""

    def __init__(self, dark):
        self.dark = dark
        self.frames = []
        self.caption = ""
        self.cursor = None

    def snap(self, win, menu=None, seconds=0.06, caption=None, cursor=None):
        if caption is not None:
            self.caption = caption
        if cursor is not None:
            self.cursor = cursor
        img = rs.render(win, menu, self.dark, 1.0)
        self.add(img, seconds)
        return img

    def add(self, img, seconds):
        out = QtGui.QImage(img.width(), img.height() + CAPTION_H, QtGui.QImage.Format.Format_RGB32)
        out.fill(QtGui.QColor("#1F1E1C"))
        p = QtGui.QPainter(out)
        p.drawImage(0, 0, img)
        if self.cursor is not None:
            draw_cursor(p, self.cursor)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        f = QtGui.QFont("DejaVu Sans")
        f.setPixelSize(19)
        p.setFont(f)
        p.setPen(QtGui.QColor("#F1EFE8"))
        p.drawText(QtCore.QRect(0, img.height(), img.width(), CAPTION_H),
                   int(QtCore.Qt.AlignmentFlag.AlignCenter), self.caption)
        p.end()
        self.frames.append((out, seconds))

    def move(self, win, menu, to, steps=8):
        start = self.cursor or QtCore.QPoint(win.width() // 2, win.height() // 2)
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)
            self.snap(win, menu, 0.04,
                      cursor=QtCore.QPoint(int(start.x() + (to.x() - start.x()) * t),
                                           int(start.y() + (to.y() - start.y()) * t)))

    def crossfade(self, a, b, steps=5):
        for i in range(1, steps + 1):
            img = QtGui.QImage(a)
            p = QtGui.QPainter(img)
            p.setOpacity(i / steps)
            p.drawImage(0, 0, b)
            p.end()
            self.add(img, 0.06)

    def write(self, path):
        with tempfile.TemporaryDirectory() as tmp:
            lines = []
            for k, (img, sec) in enumerate(self.frames):
                name = os.path.join(tmp, f"{k:04d}.png")
                img.save(name)
                lines.append(f"file '{name}'\nduration {sec:.3f}")
            lines.append(f"file '{name}'")   # concat ignores the last duration otherwise
            listing = os.path.join(tmp, "list.txt")
            with open(listing, "w") as f:
                f.write("\n".join(lines) + "\n")
            vf = (f"fps=25,scale={WIDTH}:-1:flags=lanczos,split[a][b];"
                  "[a]palettegen=stats_mode=diff:max_colors=200[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing,
                            "-vf", vf, "-loop", "0", path], check=True)
        print(path, f"{os.path.getsize(path) / 1e6:.1f} MB")


def fresh(result, dark, state="idle"):
    return rs.build(state, result, dark)[0]


def done(win):
    win.close()
    win.deleteLater()
    QtWidgets.QApplication.processEvents()


def film_translate(result, dark, caption):
    """Idle -> click Translate -> spinner + flash -> overlays fade in."""
    film = Film(dark)
    win = fresh(result, dark)
    btn = win.toolbar.translate_btn
    film.snap(win, seconds=1.0, caption=caption, cursor=QtCore.QPoint(win.width() // 2, win.height() // 3))
    film.move(win, None, pos_of(win, btn, 0.6, 0.6))
    film.snap(win, seconds=0.25)
    c = win.central
    win.set_busy(True)
    win.hide_capture_ui()
    c.show_status("OCR + translating…", 3000)
    rs.settle(win)
    win._keep_flash = True
    btn._spin.stop()
    c._breath_anim.stop()
    c._flash_anim.stop()
    for k in range(16):
        btn._set_angle(k * 30)
        c._on_breath(0.5 - 0.5 * abs(k / 15 * 2 - 1))
        c._on_flash(max(0.0, 1.0 - k * 0.2))
        last = film.snap(win)
    win.set_busy(False)
    c.stop_flash()
    win.on_translation_finished(result)
    QtWidgets.QApplication.processEvents()
    rs.settle(win)
    final = rs.render(win, None, dark, 1.0)
    film.crossfade(last, final)
    film.snap(win, seconds=3.0)
    done(win)
    return film


def film_interact(result):
    """Hover a translation, click to copy, hold Alt to peek at the original."""
    film = Film(False)
    win = fresh(result, False, "translated")
    label = max(win.overlay_labels, key=lambda lb: lb.font_px)   # the page title
    film.snap(win, seconds=0.8, caption="Click a translation to copy it",
              cursor=QtCore.QPoint(win.width() * 2 // 3, win.height() * 2 // 3))
    film.move(win, None, pos_of(win, label, 0.3, 0.6))
    label._hover = True
    label.update()
    film.snap(win, seconds=0.6)
    win.copy_overlay_text(label)
    label._ring_anim.stop()
    rs.settle(win)
    for v in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3):
        label._set_ring(v)
        film.snap(win, seconds=0.08)
    film.snap(win, seconds=1.2)
    label._hover = False
    label._set_ring(0.0)
    win.central.hide_status()
    film.snap(win, seconds=0.6, caption="Hold Alt to peek at the original")
    for lb in win.overlay_labels:
        lb.hide()
    film.snap(win, seconds=1.6)
    for lb in win.overlay_labels:
        lb.show()
    film.snap(win, seconds=1.2)
    done(win)
    return film


def film_toolbar(result):
    """Language menu, pin (always on top), keyboard shortcuts."""
    film = Film(False)
    win = fresh(result, False)
    tb = win.toolbar
    film.snap(win, seconds=0.6, caption="Pick the source language",
              cursor=QtCore.QPoint(win.width() // 2, win.height() // 2))
    film.move(win, None, pos_of(win, tb.chip, 0.5, 0.6))
    win.refresh_toolbar()
    win._popup_lang_menu()
    menu = win.lang_menu
    QtWidgets.QApplication.processEvents()
    film.snap(win, menu, seconds=0.5)
    german = win.lang_actions["de"]
    target = menu.actionGeometry(german).center() + menu.geometry().topLeft() - win.geometry().topLeft()
    film.move(win, menu, target)
    menu.setActiveAction(german)
    film.snap(win, menu, seconds=0.6)
    menu.hide()
    win.set_source_lang("de")
    rs.settle(win)
    film.snap(win, seconds=1.3)
    win.set_source_lang("auto")
    win.central.hide_status()

    film.snap(win, seconds=0.3, caption="Pin the window on top (T)")
    film.move(win, None, pos_of(win, tb.pin_btn, 0.6, 0.6))
    tb.pin_btn.set_toggled(True)
    win.central.show_status("Always on top: on", 1500)
    rs.settle(win)
    film.snap(win, seconds=1.3)
    tb.pin_btn.set_toggled(False)
    win.central.hide_status()

    film.snap(win, seconds=0.3, caption="Keyboard shortcuts")
    film.move(win, None, pos_of(win, tb.more_btn, 0.6, 0.6))
    win._popup_more_menu()
    menu = win.more_menu
    QtWidgets.QApplication.processEvents()
    film.snap(win, menu, seconds=0.4)
    target = (menu.actionGeometry(win.shortcuts_action).center() + menu.geometry().topLeft()
              - win.geometry().topLeft())
    film.move(win, menu, target)
    menu.setActiveAction(win.shortcuts_action)
    film.snap(win, menu, seconds=0.5)
    menu.hide()
    win.show_shortcuts()
    rs.settle(win)
    film.snap(win, seconds=2.5)
    done(win)
    return film


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    light = translate_page(rs.page_background(False)[1])
    film_translate(light, False, "Space or Translate: capture, OCR and translate in place").write(
        os.path.join(out_dir, "translate.gif"))
    film_interact(light).write(os.path.join(out_dir, "interact.gif"))
    film_toolbar(light).write(os.path.join(out_dir, "toolbar.gif"))


if __name__ == "__main__":
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs"))
