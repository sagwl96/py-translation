import subprocess
import sys

import pytest

from pytranslate.__main__ import config_from_args
from pytranslate.config import CONFIG, Config, apply_config


def test_defaults():
    assert config_from_args([]) == Config()


def test_all_flags():
    cfg = config_from_args(["--src", "de", "--tgt", "fr", "--online", "--min-conf", "55"])
    assert (cfg.source_lang, cfg.target_lang, cfg.offline, cfg.min_ocr_conf) == \
        ("de", "fr", False, 55)


def test_offline_flag_and_last_exclusive():
    assert config_from_args(["--offline"]).offline is True
    with pytest.raises(SystemExit):
        config_from_args(["--online", "--offline"])


def test_on_top_flag():
    assert config_from_args([]).on_top is False
    assert config_from_args(["--on-top"]).on_top is True


def test_ocr_flag_removed():
    with pytest.raises(SystemExit):
        config_from_args(["--ocr", "tesseract"])


def test_apply_config_updates_shared_instance(monkeypatch):
    for f in ("source_lang", "offline", "min_ocr_conf"):
        monkeypatch.setattr(CONFIG, f, getattr(CONFIG, f))   # restore on teardown
    apply_config(Config(source_lang="de", offline=False, min_ocr_conf=7))
    assert (CONFIG.source_lang, CONFIG.offline, CONFIG.min_ocr_conf) == ("de", False, 7)


@pytest.mark.parametrize("cmd", [["-m", "pytranslate", "--help"], ["main.py", "--help"]])
def test_help_does_not_open_window(cmd):
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable] + cmd, cwd=root, capture_output=True, text=True, timeout=60,
                       env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert r.returncode == 0, r.stderr
    for flag in ("--src", "--tgt", "--online", "--offline", "--min-conf", "--on-top"):
        assert flag in r.stdout


def test_ocr_lang_flag():
    assert config_from_args([]).ocr_lang == ""
    assert config_from_args(["--ocr-lang", "eng+deu"]).ocr_lang == "eng+deu"


def test_beam_flag():
    assert config_from_args([]).beam == 2
    assert config_from_args(["--beam", "4"]).beam == 4
