"""Render the synthetic web-page fixture, run the real OCR/layout pipeline with a fake
translator, composite the MainWindow overlays on top and save a PNG plus metrics.

    QT_QPA_PLATFORM=offscreen uv run python scripts/render_overlays.py OUT.png [--button orange]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets  # noqa: E402

from tests import helpers  # noqa: E402


def _inter(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return max(0, x2 - x1) * max(0, y2 - y1)


def label_rect(label):
    return (label.x(), label.y(), label.width(), label.height())


def font_px(label):
    v = getattr(label, "font_px", None)
    if v:
        return v
    m = re.search(r"font-size:\s*(\d+)px", label.styleSheet())
    return int(m.group(1)) if m else label.font().pixelSize()


def analyze(result, regions, win):
    """Metrics of one run: dicts keyed by name."""
    labels = win.overlay_labels
    rects = [label_rect(lb) for lb in labels]
    pairs = [(i, j) for i in range(len(rects)) for j in range(i + 1, len(rects))
             if _inter(rects[i], rects[j]) > 0]
    per_region = []
    for reg in regions:
        r = reg["rect"]
        hits = [i for i, it in enumerate(result) if _inter(it["par_rect"], r) > 0.5 * r[2] * r[3]]
        entry = {"text": reg["text"][:40], "px": reg["px"], "n_pars": len(hits)}
        if hits:
            i = max(hits, key=lambda k: _inter(result[k]["par_rect"], r))
            entry["merged_with_others"] = sum(
                1 for o in regions if o is not reg and
                _inter(result[i]["par_rect"], o["rect"]) > 0.5 * o["rect"][2] * o["rect"][3])
            entry["ratio"] = round(font_px(labels[i]) / reg["px"], 2)
            pr = result[i]["par_rect"]
            lr = rects[i]
            entry["bg_err"] = max(abs(a - b) for a, b in zip(result[i].get("bg") or (0, 0, 0), reg["bg"]))
            entry["within_rect"] = (lr[0] >= pr[0] - 4 and lr[1] >= pr[1] - 4 and
                                    lr[0] + lr[2] <= pr[0] + pr[2] + 4 and
                                    lr[1] + lr[3] <= pr[1] + pr[3] + 4)
            entry["covers_rect"] = (lr[0] <= pr[0] + 1 and lr[1] <= pr[1] + 1 and
                                    lr[0] + lr[2] >= pr[0] + pr[2] - 1 and
                                    lr[1] + lr[3] >= pr[1] + pr[3] - 1)
        per_region.append(entry)
    return {"n_regions": len(regions), "n_pars": len(result), "overlap_pairs": len(pairs),
            "pairs": pairs, "regions": per_region}


def run(out_path=None, dpr=1.0, button=None):
    from pytranslate.ui import MainWindow
    bgr, regions = helpers.render_web_page(button=button)
    result = helpers.run_page_pipeline(bgr, dpr)
    win = MainWindow()
    win.resize(bgr.shape[1], bgr.shape[0])
    win.show()
    win.on_translation_finished(result)
    QtWidgets.QApplication.processEvents()
    img = helpers.render_overlays(win, bgr)
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        img.save(out_path)
    return win, bgr, regions, result, analyze(result, regions, win)


if __name__ == "__main__":
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    out = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else None
    btn = sys.argv[sys.argv.index('--button') + 1] if '--button' in sys.argv else None
    _, _, _, _, m = run(out, button=btn)
    print(f"regions={m['n_regions']} paragraphs={m['n_pars']} overlapping_label_pairs={m['overlap_pairs']}")
    for r in m["regions"]:
        print(r)
