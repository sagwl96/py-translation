"""Model resolution and the setup script's pure helpers (all offline)."""
import importlib.util
import os
import zipfile

import pytest

from pytranslate import ocr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_setup():
    spec = importlib.util.spec_from_file_location("setup_models", os.path.join(ROOT, "scripts", "setup_models.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


setup_models = _load_setup()


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setenv("PYTRANSLATE_NO_LEGACY_PATHS", "1")   # ignore the system tessdata of the dev machine
    return tmp_path


def test_find_tessdata_looks_in_app_data_dir(clean_env):
    assert ocr.find_tessdata("deu") == "" and not ocr.has_tessdata("deu")
    d = clean_env / "py-translation" / "tessdata"
    d.mkdir(parents=True)
    (d / "deu.traineddata").write_bytes(b"x")
    assert ocr.find_tessdata("deu") == str(d)
    assert ocr.has_tessdata("deu") and not ocr.has_tessdata("eng+deu")


def test_tessdata_prefix_wins_over_app_dir(clean_env, monkeypatch):
    app = clean_env / "py-translation" / "tessdata"
    env = clean_env / "env"
    for d in (app, env):
        d.mkdir(parents=True)
        (d / "deu.traineddata").write_bytes(b"x")
    monkeypatch.setenv("TESSDATA_PREFIX", str(env))
    assert ocr.find_tessdata("deu") == str(env)


def test_pick_package_newest_matching_pair():
    index = [
        {"code": "translate-de_en", "from_code": "de", "to_code": "en", "package_version": "1.2", "links": ["a"]},
        {"code": "translate-de_en", "from_code": "de", "to_code": "en", "package_version": "1.10", "links": ["b"]},
        {"code": "translate-de_en", "from_code": "de", "to_code": "en", "package_version": "1.3", "links": ["c"]},
        {"code": "translate-en_de", "from_code": "en", "to_code": "de", "package_version": "9.0", "links": ["d"]},
        {"code": "translate-de_en", "from_code": "de", "to_code": "en", "package_version": "2.0", "links": []},
    ]
    best = setup_models.pick_package(index, "de", "en")
    assert best["links"] == ["b"]
    assert setup_models.package_dirname(best) == "translate-de_en-1_10"
    assert setup_models.pick_package(index, "de", "fr") is None


def test_safe_extract_rejects_path_traversal(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escape.txt", "x")
    with pytest.raises(RuntimeError, match="unsafe path"):
        setup_models.safe_extract(str(z), str(tmp_path / "out"))
    assert not (tmp_path / "escape.txt").exists()


def test_extract_and_find_package_root(tmp_path):
    z = tmp_path / "p.argosmodel"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("translate-de_en-1_3/metadata.json", "{}")
        zf.writestr("translate-de_en-1_3/model/model.bin", "x")
    out = tmp_path / "out"
    setup_models.safe_extract(str(z), str(out))
    assert setup_models.find_package_root(str(out)) == str(out / "translate-de_en-1_3")


def test_install_is_skipped_when_model_and_tessdata_exist(clean_env, capsys, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network used although everything is installed")

    monkeypatch.setattr(setup_models.urllib.request, "urlopen", no_network)
    pkg = clean_env / "py-translation" / "models" / "translate-de_en-1_3"
    (pkg / "model").mkdir(parents=True)
    (pkg / "sentencepiece.model").write_bytes(b"x")
    tess = clean_env / "py-translation" / "tessdata"
    tess.mkdir(parents=True)
    (tess / "deu.traineddata").write_bytes(b"x")
    assert setup_models.main([]) == 0
    out = capsys.readouterr().out
    assert out.count("already") == 2
