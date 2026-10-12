"""Offline benchmark of the capture pipeline on rendered German fixtures.

    QT_QPA_PLATFORM=offscreen uv run python scripts/bench.py [--reps N]

Prints, per fixture, the median time of each stage (preprocess, OCR, layout,
translate warm, total), the number of Tesseract calls, words recognised,
key-word hits and paragraph count. Needs no network (Argos model must be installed).
"""
import argparse
import os
import statistics
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6 import QtWidgets  # noqa: E402

from pytranslate import layout, ocr, translate  # noqa: E402
from pytranslate.config import CONFIG  # noqa: E402
from tests.helpers import render_text_image  # noqa: E402

LARGE = [
    "Guten Morgen, wie geht es Ihnen heute? Das Wetter ist sehr schön und warm.",
    "Wir gehen später in den Park spazieren und trinken dort einen Kaffee.",
    "Die Kinder spielen im Garten und die Eltern sitzen auf der Terrasse.",
    "Der Zug nach Berlin fährt jeden Morgen um acht Uhr vom Hauptbahnhof ab.",
    "Ich möchte gern einen Tisch für vier Personen reservieren, bitte.",
    "",
    "Das neue Restaurant in der Innenstadt bietet frisches Gemüse und Fisch an.",
    "Am Wochenende besuchen wir unsere Freunde in der Nähe von München.",
    "Die Bibliothek ist montags bis freitags von neun bis achtzehn Uhr geöffnet.",
    "Bitte schließen Sie die Tür, wenn Sie den Raum verlassen.",
    "",
    "Mein Bruder arbeitet als Ingenieur in einer großen Firma für Maschinenbau.",
    "Im Sommer fahren wir oft mit dem Fahrrad an den See und schwimmen dort.",
    "Vielen Dank für Ihre Hilfe, das war wirklich sehr freundlich von Ihnen.",
]
LARGE_KEYS = ["morgen", "wetter", "park", "kaffee", "kinder", "garten", "terrasse", "berlin",
              "hauptbahnhof", "tisch", "personen", "restaurant", "gemüse", "wochenende",
              "freunde", "bibliothek", "montags", "tür", "bruder", "ingenieur", "sommer",
              "fahrrad", "vielen", "hilfe"]
SMALL = ["Guten Morgen, wie geht es Ihnen heute?",
         "Das Wetter ist heute sehr schön und warm.",
         "Wir gehen später in den Park spazieren."]
SMALL_KEYS = ["guten", "morgen", "wetter", "heute", "schön", "später", "park", "spazieren"]
LEFT = ["Der Hund läuft schnell", "durch den grünen Wald", "und bellt laut",
        "Er springt über den Bach", "und jagt einen Hasen", "bis zum Abend"]
RIGHT = ["Die Katze schläft ruhig", "auf dem weichen Sofa", "und träumt süß",
         "Sie wacht erst spät auf", "und trinkt etwas Milch", "danach geht sie hinaus"]
TWO_KEYS = ["hund", "wald", "bellt", "bach", "hasen", "abend",
            "katze", "sofa", "träumt", "milch", "spät", "hinaus"]


def fixtures():
    return [
        ("large", render_text_image(LARGE, size=(1400, 700), font_px=18, margin=30,
                                    line_spacing=1.5), LARGE_KEYS),
        ("small", render_text_image(SMALL, size=(420, 110), font_px=7, margin=8,
                                    line_spacing=1.4), SMALL_KEYS),
        ("two-col", render_text_image(LEFT + RIGHT, size=(1000, 300), columns=2,
                                      font_px=22), TWO_KEYS),
    ]


def order(name, ptext):
    """Two-column check: every left-column key word precedes every right-column one."""
    if name != "two-col":
        return "-"
    left = [ptext.find(k) for k in TWO_KEYS[:6]]
    right = [ptext.find(k) for k in TWO_KEYS[6:]]
    return "ok" if min(left) >= 0 and min(right) >= 0 and max(left) < min(right) else "INTERLEAVED"


def run_once(img, calls):
    n0 = len(calls)
    t0 = time.perf_counter()
    small, sf = ocr.preprocess_image(img)
    t1 = time.perf_counter()
    lines = ocr.perform_ocr(small, sf)
    t2 = time.perf_counter()
    pars = layout.group_lines_to_paragraphs(lines)
    t3 = time.perf_counter()
    text = " ".join(l["text"] for l in lines).lower()
    translate.clear_translation_cache()
    translate.get_argos_translation("de", CONFIG.target_lang)
    translate.translate_paragraphs([dict(p) for p in pars])
    t4 = time.perf_counter()
    return {"pre": t1 - t0, "ocr": t2 - t1, "layout": t3 - t2, "tr": t4 - t3, "total": t4 - t0,
            "calls": len(calls) - n0, "words": len(text.split()), "text": text, "pars": len(pars),
            "ptext": " | ".join(p["text"] for p in pars).lower()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    args = ap.parse_args()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setApplicationName("bench")   # keep a reference alive

    CONFIG.source_lang = "de"   # deterministic: skip per-paragraph detection
    calls = []
    orig = ocr._recognize_words

    def counted(*a, **k):
        calls.append(1)
        return orig(*a, **k)
    ocr._recognize_words = counted

    translate.get_argos_translation("de", CONFIG.target_lang)
    translate.translate_text("Hallo Welt, wie geht es dir?", "de")   # warm the model
    print(f"{'fixture':8} {'pre':>6} {'ocr':>7} {'layout':>7} {'transl':>7} {'total':>7}"
          f"  {'calls':>5} {'words':>5} {'keys':>6} {'pars':>4}  column order   (median ms)")
    for name, img, keys in fixtures():
        runs = [run_once(img, calls) for _ in range(args.reps)]
        med = lambda k: statistics.median(r[k] for r in runs) * 1000
        r = runs[-1]
        hits = sum(1 for k in keys if k in r["text"])
        print(f"{name:8} {med('pre'):6.1f} {med('ocr'):7.1f} {med('layout'):7.2f} {med('tr'):7.1f} "
              f"{med('total'):7.1f}  {r['calls']:5d} {r['words']:5d} {hits:>3}/{len(keys):<2} {r['pars']:4d}  {order(name, r['ptext'])}")


if __name__ == "__main__":
    main()
