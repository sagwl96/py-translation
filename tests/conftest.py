import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


import pytest


@pytest.fixture(autouse=True)
def _fresh_translation_cache():
    from pytranslate import translate, worker
    translate.clear_translation_cache()
    worker.clear_capture_cache()
    yield
    translate.clear_translation_cache()
    worker.clear_capture_cache()


@pytest.fixture(scope="session")
def qapp():
    from PyQt6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
