"""Runtime configuration: one dataclass, one shared instance (CONFIG)."""
from dataclasses import dataclass, fields


@dataclass
class Config:
    source_lang: str = 'auto'      # 'auto' = detect per paragraph ('de' or 'en'), or a fixed code like 'de'
    target_lang: str = 'en'
    offline: bool = True           # True = Argos only (offline, default), False = Google (--online)
    max_ocr_width: int = 2560      # downscale only captures wider than this
    min_glyph_height: int = 7      # estimated glyph height (px) below which OCR runs on a x2 upscale
    ocr_upscale: int = 2
    ocr_threshold_method: int = 2  # Tesseract thresholding: 0 Otsu, 1 Leptonica adaptive, 2 Sauvola (2 keeps text on coloured buttons/bars)
    column_gap_factor: float = 2.0  # split an OCR line at word gaps > this x median word height
    min_ocr_conf: int = 40
    beam: int = 2                  # Argos beam size (4 is Argos' default; 2 is ~2x faster, same quality)
    ocr_lang: str = ''             # Tesseract language(s), e.g. 'deu' or 'eng+deu'; '' = by source language
    capture_delay_ms: int = 50     # let the compositor repaint after hiding overlays/toast
    save_captures: str = ''        # directory: save every capture (.png) + OCR/translation dump (.json); '' = off
    on_top: bool = False           # start with the window always on top


# Shared instance read by every module at call time (so tests/CLI can mutate it).
CONFIG = Config()


def apply_config(new):
    """Copy all fields of `new` into the shared CONFIG instance."""
    for f in fields(new):
        setattr(CONFIG, f.name, getattr(new, f.name))
