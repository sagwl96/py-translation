"""Design tokens for the floating-frame UI: every colour and size is defined once, here."""
from PyQt6 import QtGui

ACCENT = "#7F77DD"
ACCENT_HOVER = "#9C95E8"
ACCENT_DEEP = "#534AB7"
CHIP_TEXT = "#EEEDFE"
INK = "#F1EFE8"
PILL_BG = "#1F1E1C"
CORAL = "#D85A30"
WHITE = "#FFFFFF"

FRAME_RADIUS = 14
FRAME_STROKE = 2.0
PILL_H = 36
PILL_RADIUS = 18
BUTTON = 28
ICON = 20
GAP = 4
OVERLAY_RADIUS = 6

HINT_ALPHA = 232        # ~91 %: 80 % let page text show through the words
PILL_ALPHA = 235        # 92 %
FLASH_MS = 250
BREATH_MS = 1200
HINT_FADE_MS = 150
TOAST_IN_MS = 120
TOAST_OUT_MS = 200


def qcolor(hex_rgb, alpha=255):
    c = QtGui.QColor(hex_rgb)
    c.setAlpha(int(alpha))
    return c


MENU_QSS = f"""
QMenu {{
    background-color: {PILL_BG};
    color: {INK};
    border: 1px solid rgba(255, 255, 255, 26);
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 18px 7px 8px;
    border-radius: 6px;
    margin: 1px 0;
}}
QMenu::item:selected {{ background-color: {ACCENT_DEEP}; color: {CHIP_TEXT}; }}
QMenu::icon {{ padding-left: 6px; }}
QMenu::separator {{ height: 1px; background: rgba(255, 255, 255, 26); margin: 5px 6px; }}
QToolTip {{
    background-color: {PILL_BG};
    color: {INK};
    border: 1px solid rgba(255, 255, 255, 26);
    padding: 4px 8px;
    border-radius: 6px;
}}
"""
