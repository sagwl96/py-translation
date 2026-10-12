"""--save-captures: dump every capture and what the pipeline made of it, so a failing real
capture can be turned into a test fixture."""
import dataclasses
import datetime
import json
import os

import cv2

from .config import CONFIG


def _plain(o):
    """JSON-friendly copy (tuples -> lists, numpy scalars -> python numbers)."""
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if hasattr(o, 'item') and not isinstance(o, (str, bytes)):
        try:
            return o.item()
        except Exception:
            pass
    return o


def save_capture(directory, img_bgr, **info):
    """Write <timestamp>.png (the BGR capture) and <timestamp>.json (settings, dpr and
    whatever is passed in `info`: ocr_lines, paragraphs, result, error, ...) into `directory`.
    Returns the common path stem. Never raises: debugging must not break a capture."""
    try:
        os.makedirs(directory, exist_ok=True)
        stem = os.path.join(directory, datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        cv2.imwrite(stem + ".png", img_bgr)
        meta = {"image": os.path.basename(stem) + ".png", "shape": list(img_bgr.shape),
                "settings": dataclasses.asdict(CONFIG)}
        meta.update(_plain(info))
        with open(stem + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return stem
    except Exception as e:   # pragma: no cover - best effort
        print("save_captures failed:", e)
        return None
