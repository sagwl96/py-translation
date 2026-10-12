"""Test helpers: render text to a BGR numpy image with Qt (offscreen)."""
from PyQt6 import QtCore, QtGui

from pytranslate.capture import qimage_to_bgr


def render_text_image(lines, size=(900, 400), color=(0, 0, 0), columns=1,
                      bg=(255, 255, 255), font_family="DejaVu Sans", font_px=28,
                      margin=30, line_spacing=1.5):
    """Render `lines` (list of str) onto a bg-coloured canvas, return BGR array.

    columns=1: one column. columns=N: lines are split into N equal consecutive
    chunks, drawn left to right as side-by-side columns sharing the same top y.
    `color`/`bg` are (R, G, B). Requires a QGuiApplication to exist.
    """
    w, h = size
    img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor(*bg))
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
    font = QtGui.QFont(font_family)
    font.setPixelSize(font_px)
    p.setFont(font)
    p.setPen(QtGui.QColor(*color))
    step = int(font_px * line_spacing)
    per_col = -(-len(lines) // columns)
    col_w = (w - 2 * margin) // columns
    for c in range(columns):
        x = margin + c * col_w
        for i, text in enumerate(lines[c * per_col:(c + 1) * per_col]):
            y = margin + i * step
            p.drawText(QtCore.QRect(x, y, col_w, step), QtCore.Qt.AlignmentFlag.AlignLeft
                       | QtCore.Qt.AlignmentFlag.AlignVCenter, text)
    p.end()
    return qimage_to_bgr(img)


def words_from_fixture(extra=()):
    """Word tuples (text, conf, left, top, w, h, block, par, line) for ocr._recognize_words,
    recorded from tests/fixtures/tess_two_lines.json (level-5 rows only)."""
    import json
    import os
    with open(os.path.join(os.path.dirname(__file__), "fixtures", "tess_two_lines.json")) as f:
        d = json.load(f)
    rows = [(d["text"][i], float(d["conf"][i]), d["left"][i], d["top"][i], d["width"][i], d["height"][i],
             d["block_num"][i], d["par_num"][i], d["line_num"][i])
            for i in range(len(d["text"])) if d["level"][i] == 5]
    return rows + list(extra)


# ---------------------------------------------------------------------------
# Synthetic web page (a made-up library page with coloured cards)
# ---------------------------------------------------------------------------

PAGE_SIZE = (1050, 650)

# (German text, English translation used by the fake translator; deliberately
# sometimes longer than the source so fitting is exercised)
PAGE_TRANSLATIONS = {
    "Willkommen in der Stadtbibliothek": "Welcome to the city library",
    "Zuletzt aktualisiert am 08. Okt. 2024 von Erika Musterfrau • 2 Minuten Lesezeit":
        "Last updated on Oct 08, 2024 by Erika Musterfrau • 2 minute read",
    "Hier finden Sie alles rund um Ausleihe, Öffnungszeiten und Veranstaltungen.":
        "Here you will find everything about lending, opening hours and events.",
    "Bibliothek durchsuchen": "Search the library",
    "Unsere Angebote": "Our services",
    "Öffnungszeiten und Anfahrt": "Opening hours and directions",
    "Montag bis Freitag von 9 bis 19 Uhr": "Monday to Friday from 9 am to 7 pm",
    "Samstag von 10 bis 14 Uhr": "Saturday from 10 am to 2 pm",
    "An Feiertagen geschlossen": "Closed on public holidays",
    "Ausleihe": "Lending",
    "Bis zu zwanzig Medien gleichzeitig ausleihen": "Borrow up to twenty items at the same time",
    "Rückgaben sind rund um die Uhr am Automaten vor dem Haupteingang möglich":
        "Returns are possible around the clock at the machine in front of the main entrance",
    "Veranstaltungen und Kurse": "Events and courses",
    "Lesestunde für Kinder": "Story time for children",
    "Sprachcafé am ersten Freitag im Monat": "Language café on the first Friday of the month",
    "Programm als PDF herunterladen": "Download the programme as a PDF",
    "Kontakt und Hilfe": "Contact and help",
    "Häufige Fragen": "Frequently asked questions",
    "Schreiben Sie uns eine Nachricht": "Send us a message",
    "So finden Sie zu uns": "How to find us",
    "Jetzt Mitglied werden": "Become a member now",
}


def _page_elements():
    """Ground-truth text blocks: (text, (x, y, w, h) of the box the text is drawn in,
    pixel size, bold, text colour, lines) where `lines` is the list of drawn lines."""
    E = []

    def add(lines, x, y, px, bold=False, color=(30, 30, 30), step=None):
        step = step or int(px * 1.3)
        E.append({"text": " ".join(lines), "lines": lines, "x": x, "y": y, "px": px,
                  "bold": bold, "color": color, "step": step})

    add(["Willkommen in der Stadtbibliothek"], 22, 45, 28, color=(20, 20, 20))
    add(["Zuletzt aktualisiert am 08. Okt. 2024 von Erika Musterfrau • 2 Minuten Lesezeit"],
        22, 79, 11, color=(90, 90, 90))
    add(["Hier finden Sie alles rund um Ausleihe, Öffnungszeiten und Veranstaltungen."], 22, 128, 13)
    add(["Bibliothek durchsuchen"], 22, 170, 18)
    add(["Unsere Angebote"], 22, 264, 20, color=(20, 20, 20))
    cards = [
        (22, 313, (127, 127, 181), "Öffnungszeiten und Anfahrt",
         [["Montag bis Freitag von 9 bis 19 Uhr"], ["Samstag von 10 bis 14 Uhr"],
          ["An Feiertagen geschlossen"]]),
        (533, 313, (163, 212, 123), "Ausleihe",
         [["Bis zu zwanzig Medien gleichzeitig ausleihen"],
          ["Rückgaben sind rund um die Uhr am Automaten vor dem",
           "Haupteingang möglich"]]),
        (22, 487, (232, 205, 122), "Veranstaltungen und Kurse",
         [["Lesestunde für Kinder"], ["Sprachcafé am ersten Freitag im Monat"],
          ["Programm als PDF herunterladen"]]),
        (533, 487, (232, 205, 122), "Kontakt und Hilfe",
         [["Häufige Fragen"], ["Schreiben Sie uns eine Nachricht"],
          ["So finden Sie zu uns"]]),
    ]
    return E, cards


BUTTON_COLORS = {"orange": (238, 118, 80), "blue": (61, 122, 184), "dark blue": (30, 70, 140),
                 "yellow": (240, 200, 60), "purple": (127, 127, 181), "green": (163, 212, 123)}
BUTTON_TEXT = "Jetzt Mitglied werden ↗"


def _draw_button(p, rect, rgb, px, text=BUTTON_TEXT, font_family="DejaVu Sans", fg=(0, 0, 0)):
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    p.setBrush(QtGui.QColor(*rgb))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.drawRoundedRect(QtCore.QRectF(*rect), 3, 3)
    f = QtGui.QFont(font_family)
    f.setPixelSize(px)
    p.setFont(f)
    p.setPen(QtGui.QColor(*fg))
    p.drawText(QtCore.QRect(*rect), QtCore.Qt.AlignmentFlag.AlignCenter, text)


def render_button(color="orange", px=13, size=(380, 50), text=BUTTON_TEXT):
    """White page with one coloured button (black text) in the middle; returns BGR array.
    `color` is a BUTTON_COLORS key or an (r, g, b) tuple."""
    rgb = BUTTON_COLORS.get(color, color)
    w, h = size
    img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor(255, 255, 255))
    p = QtGui.QPainter(img)
    _draw_button(p, (50, 8, 205, 30), rgb, px, text)
    p.end()
    return qimage_to_bgr(img)


def render_web_page(font_family="DejaVu Sans", button=None):
    """Render a synthetic German help page (heading, small meta line, body text, search
    box, 2x2 cards with coloured header bars and links) of a made-up city library.

    Returns (bgr_image, regions); regions is a list of ground-truth paragraphs
    {'text', 'rect': (x, y, w, h), 'px', 'kind', 'bg': (r, g, b)} where rect is the tight box of the drawn
    text and kind in {'title','meta','body','search','heading','card_header','link'}.
    Requires a QGuiApplication.
    """
    w, h = PAGE_SIZE
    img = QtGui.QImage(w, h, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor(255, 255, 255))
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
    regions = []

    def draw(lines, x, y, px, bold, color, step, kind, bg=(255, 255, 255)):
        f = QtGui.QFont(font_family)
        f.setPixelSize(px)
        f.setBold(bold)
        p.setFont(f)
        p.setPen(QtGui.QColor(*color))
        fm = QtGui.QFontMetrics(f)
        right = 0
        for i, line in enumerate(lines):
            p.drawText(x, y + i * step + fm.ascent(), line)
            right = max(right, fm.horizontalAdvance(line))
        regions.append({"text": " ".join(lines), "px": px, "kind": kind,
                        "rect": (x, y, right, step * (len(lines) - 1) + fm.height()), "bg": bg})

    E, cards = _page_elements()
    kinds = ["title", "meta", "body", "search", "heading"]
    for el, kind in zip(E, kinds):
        draw(el["lines"], el["x"], el["y"], el["px"], el["bold"], el["color"], el["step"], kind)

    # search box
    p.setPen(QtGui.QColor(90, 100, 120))
    p.setBrush(QtGui.QColor(255, 255, 255))
    p.drawRect(22, 205, 240, 27)
    p.setBrush(QtGui.QColor(235, 237, 245))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.drawRoundedRect(267, 203, 38, 30, 3, 3)
    p.setPen(QtGui.QPen(QtGui.QColor(40, 60, 120), 2))
    p.drawEllipse(279, 211, 10, 10)
    p.drawLine(288, 220, 293, 225)

    for x, y, bar, header, links in cards:
        ch = 142
        p.setPen(QtGui.QColor(20, 20, 20))
        p.setBrush(QtGui.QColor(255, 255, 255))
        p.drawRect(x, y, 491, ch)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(*bar))
        p.drawRect(x + 1, y + 1, 490, 40)
        draw([header], x + 11, y + 12, 14, True, (30, 30, 70), 18, "card_header", bg=bar)
        ly = y + 55
        for lines in links:
            draw(lines, x + 11, ly, 13, False, (25, 60, 140), 17, "link")
            ly += 17 * (len(lines) - 1) + 31
    if button:   # coloured button (black text) on the white page, top right
        rect = (700, 60, 220, 36)
        _draw_button(p, rect, BUTTON_COLORS.get(button, button), 14, font_family=font_family)
        regions.append({"text": BUTTON_TEXT, "px": 14, "kind": "button", "rect": rect,
                        "bg": BUTTON_COLORS.get(button, button)})
    p.end()
    return qimage_to_bgr(img), regions


def fake_translate(text):
    """Deterministic stand-in for the translator: known page strings -> English,
    otherwise a fuzzy match, otherwise the upper-cased input."""
    import difflib
    if text in PAGE_TRANSLATIONS:
        return PAGE_TRANSLATIONS[text]
    m = difflib.get_close_matches(text, list(PAGE_TRANSLATIONS), n=1, cutoff=0.8)
    return PAGE_TRANSLATIONS[m[0]] if m else text.upper()


def run_page_pipeline(bgr, dpr=1.0):
    """Run the real worker (tesserocr OCR + layout + result building) synchronously with
    fake_translate instead of a network translator. Returns the result_data list."""
    from pytranslate import worker as worker_mod

    class _W(worker_mod.TranslationWorker):
        def _translate_paragraphs(self, paragraphs, report=None):
            for par in paragraphs:
                par['text'] = fake_translate(par['text'])
            return paragraphs

    worker_mod.clear_capture_cache()
    out = []
    w = _W(bgr, dpr=dpr)
    w.finished_translation.connect(out.append)
    w.run()
    return out[0] if out else []


def render_overlays(win, bgr):
    """Paint the window's overlay labels over `bgr`; returns a QImage (opaque)."""
    from pytranslate.capture import bgr_to_qimage
    img = bgr_to_qimage(bgr)
    p = QtGui.QPainter(img)
    for label in win.overlay_labels:
        anim = getattr(label, "anim_ref", None)
        if anim is not None:
            anim.stop()
        label.setGraphicsEffect(None)
        label.render(p, QtCore.QPoint(label.x(), label.y()))
    p.end()
    return img
