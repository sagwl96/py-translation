import json
import os

import cv2

from pytranslate.__main__ import config_from_args
from pytranslate.config import CONFIG
from tests import helpers


def test_flag_parsed():
    assert config_from_args([]).save_captures == ""
    assert config_from_args(["--save-captures", "/tmp/x"]).save_captures == "/tmp/x"


def test_capture_saved_as_png_and_json(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "save_captures", str(tmp_path / "caps"))
    bgr, _ = helpers.render_web_page()
    result = helpers.run_page_pipeline(bgr, dpr=1.0)
    files = sorted(os.listdir(tmp_path / "caps"))
    assert len(files) == 2 and os.path.splitext(files[0])[0] == os.path.splitext(files[1])[0]
    png = cv2.imread(str(tmp_path / "caps" / [f for f in files if f.endswith(".png")][0]))
    assert png.shape == bgr.shape and (png == bgr).all()
    meta = json.loads((tmp_path / "caps" / [f for f in files if f.endswith(".json")][0]).read_text())
    assert meta["dpr"] == 1.0 and meta["settings"]["save_captures"]
    assert len(meta["ocr_lines"]) >= len(meta["paragraphs"]) == len(meta["translated"]) == len(result)
    assert "par_rect" in meta["result"][0]


def test_no_files_when_disabled(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "save_captures", "")
    monkeypatch.chdir(tmp_path)
    helpers.run_page_pipeline(helpers.render_web_page()[0])
    assert os.listdir(tmp_path) == []
