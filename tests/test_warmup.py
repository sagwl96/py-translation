import time

from pytranslate import translate
from pytranslate.config import CONFIG


class FakeArgos:
    def __init__(self):
        self.calls = []

    def translate(self, text, beam=2):
        self.calls.append(text)
        return "EN:" + text


def _setup(monkeypatch, tr, find_log, delay=0.0):
    def find(src, tgt):
        find_log.append((src, tgt))
        time.sleep(delay)
        return tr

    monkeypatch.setattr(translate, "_find_installed_argos", find)
    monkeypatch.setattr(translate, "_ARGOS_CACHE", {})
    monkeypatch.setattr(translate, "_warmup_thread", None)
    monkeypatch.setattr(CONFIG, "offline", True)
    monkeypatch.setattr(CONFIG, "source_lang", "auto")


def test_warmup_runs_once_and_first_translate_does_not_reload(monkeypatch):
    tr, finds = FakeArgos(), []
    _setup(monkeypatch, tr, finds)
    t = translate.start_warmup()
    assert t is not None
    t.join(5)
    assert finds == [("de", "en")]
    assert translate.start_warmup() is None            # only once
    assert translate.translate_text("Guten Morgen", "de") == "EN:Guten Morgen"
    assert finds == [("de", "en")]                     # no second lookup/load
    assert tr.calls[0] == "Hallo" and "Guten Morgen" in tr.calls


def test_translate_during_warmup_waits_instead_of_reloading(monkeypatch):
    tr, finds = FakeArgos(), []
    _setup(monkeypatch, tr, finds, delay=0.3)
    t = translate.start_warmup()
    t0 = time.monotonic()
    assert translate.translate_text("Hallo Welt", "de") == "EN:Hallo Welt"
    t.join(5)
    assert len(finds) == 1
    assert time.monotonic() - t0 >= 0.25


def test_start_is_nonblocking(monkeypatch):
    finds = []
    _setup(monkeypatch, FakeArgos(), finds, delay=0.5)
    t0 = time.monotonic()
    t = translate.start_warmup()
    assert time.monotonic() - t0 < 0.2
    t.join(5)


def test_warmup_skipped_in_online_mode(monkeypatch):
    finds = []
    _setup(monkeypatch, FakeArgos(), finds)
    monkeypatch.setattr(CONFIG, "offline", False)
    assert translate.start_warmup() is None
    assert finds == []


def test_warmup_miss_not_cached(monkeypatch):
    finds = []
    _setup(monkeypatch, None, finds)
    translate.start_warmup().join(5)
    assert translate._ARGOS_CACHE == {}
