"""pytranslate.mt: sentence splitter and model resolution (offline, no model needed)."""
import os

import pytest

from pytranslate import mt


@pytest.mark.parametrize("text, expected", [
    ("Guten Morgen. Wie geht es dir? Gut!", ["Guten Morgen.", "Wie geht es dir?", "Gut!"]),
    ("Das ist z.B. ein Test, d.h. kein Problem. Danke.", ["Das ist z.B. ein Test, d.h. kein Problem.", "Danke."]),
    ("Das ist z. B. Hans. Dann gehen wir.", ["Das ist z. B. Hans.", "Dann gehen wir."]),
    ("Dr. Müller wohnt in der Hauptstr. 5 in Bonn. Er kommt.", ["Dr. Müller wohnt in der Hauptstr. 5 in Bonn.", "Er kommt."]),
    ("Treffen am Hbf. Berlin, ca. 10 Uhr, inkl. Gepäck, ggf. früher. Ende.",
     ["Treffen am Hbf. Berlin, ca. 10 Uhr, inkl. Gepäck, ggf. früher.", "Ende."]),
    ("Offen Mo. Di. Mi. von 9 bis 18 Uhr, usw. Danach zu.", ["Offen Mo. Di. Mi. von 9 bis 18 Uhr, usw. Danach zu."]),
    ("Siehe vgl. Nr. 4 und bzw. u.a. Fr. Meier.", ["Siehe vgl. Nr. 4 und bzw. u.a. Fr. Meier."]),
    ("Am 08. Oktober ist es soweit. Wir freuen uns.", ["Am 08. Oktober ist es soweit.", "Wir freuen uns."]),
    ("Der 2. Weltkrieg endete 1945. Danach kam Frieden.", ["Der 2. Weltkrieg endete 1945.", "Danach kam Frieden."]),
    ("Es kostet 1.000 Euro. Das ist viel.", ["Es kostet 1.000 Euro.", "Das ist viel."]),
    ("Er sagte: „Komm her!“ Dann ging er… Und wieder.",
     ["Er sagte: „Komm her!“", "Dann ging er…", "Und wieder."]),
    ("Wirklich?! Ja. 2020 war schlimm.", ["Wirklich?!", "Ja.", "2020 war schlimm."]),
    ("Das ist gut... aber nicht genug.", ["Das ist gut... aber nicht genug."]),
    ("Volleyball: 3. Liga Frauen gewinnt. Ende.", ["Volleyball: 3. Liga Frauen gewinnt.", "Ende."]),
    ("Platz 3. Dann gehen wir.", ["Platz 3.", "Dann gehen wir."]),
    ("Version 3.5 ist da. ok", ["Version 3.5 ist da. ok"]),
    ("", []),
    ("   ", []),
    ("Ohne Punkt", ["Ohne Punkt"]),
])
def test_split_sentences(text, expected):
    assert mt.split_sentences(text) == expected


def _make_pkg(base, name):
    d = os.path.join(base, name)
    os.makedirs(os.path.join(d, "model"))
    open(os.path.join(d, "sentencepiece.model"), "w").close()
    with open(os.path.join(d, "metadata.json"), "w") as f:
        f.write('{"from_code": "de", "to_code": "en"}')
    return d


def test_find_model_prefers_app_dir_over_legacy_and_newest_version(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("PYTRANSLATE_NO_LEGACY_PATHS", raising=False)
    assert mt.find_model("de", "en") is None
    legacy = _make_pkg(str(tmp_path / "argos-translate" / "packages"), "translate-de_en-1_3")
    assert mt.find_model("de", "en") == legacy
    app_old = _make_pkg(str(tmp_path / "py-translation" / "models"), "translate-de_en-1_2")
    app_new = _make_pkg(str(tmp_path / "py-translation" / "models"), "translate-de_en-1_10")
    assert mt.find_model("de", "en") == app_new and app_old != app_new
    assert mt.find_model("en", "de") is None


def test_no_legacy_env_var_hides_argos_translate_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _make_pkg(str(tmp_path / "argos-translate" / "packages"), "translate-de_en-1_3")
    monkeypatch.setenv("PYTRANSLATE_NO_LEGACY_PATHS", "1")
    assert mt.find_model("de", "en") is None


def test_incomplete_package_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    os.makedirs(tmp_path / "py-translation" / "models" / "translate-de_en-1_3")
    assert mt.find_model("de", "en") is None


def test_default_home_without_xdg(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert mt.app_data_dir() == str(tmp_path / ".local" / "share" / "py-translation")
