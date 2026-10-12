from pytranslate import translate
from pytranslate.config import CONFIG


def _counting_google(monkeypatch):
    calls = []

    class Fake:
        def __init__(self, source, target):
            self.key = (source, target)

        def translate(self, text):
            calls.append((self.key, text))
            return f"{self.key[1]}:{text}"

    monkeypatch.setattr(translate, "GoogleTranslator", Fake)
    monkeypatch.setattr(CONFIG, "offline", False)
    return calls


def test_second_identical_call_hits_cache(monkeypatch):
    calls = _counting_google(monkeypatch)
    assert translate.translate_text("Guten Morgen", "de") == "en:Guten Morgen"
    assert len(calls) == 1
    assert translate.translate_text("Guten Morgen", "de") == "en:Guten Morgen"
    assert len(calls) == 1


def test_cache_keyed_by_src_tgt_and_text(monkeypatch):
    calls = _counting_google(monkeypatch)
    translate.translate_text("Hallo", "de")
    translate.translate_text("Hallo", "nl")
    translate.translate_text("Hallo!", "de")
    monkeypatch.setattr(CONFIG, "target_lang", "fr")
    translate.translate_text("Hallo", "de")
    assert len(calls) == 4


def test_failures_are_not_cached(monkeypatch):
    state = {"fail": True, "n": 0}

    class Flaky:
        def __init__(self, **k):
            pass

        def translate(self, text):
            state["n"] += 1
            if state["fail"]:
                raise RuntimeError("down")
            return "ok"

    monkeypatch.setattr(translate, "GoogleTranslator", Flaky)
    monkeypatch.setattr(CONFIG, "offline", False)
    try:
        translate.translate_text("x", "de")
    except RuntimeError:
        pass
    state["fail"] = False
    assert translate.translate_text("x", "de") == "ok"
    assert state["n"] == 2


def test_repeat_capture_skips_backend_via_paragraphs(monkeypatch):
    calls = _counting_google(monkeypatch)
    monkeypatch.setattr(CONFIG, "source_lang", "de")
    mk = lambda: [{"text": "Guten Morgen", "par_rect": (0, 0, 1, 1), "line_rects": [(0, 0, 1, 1)]}]
    translate.translate_paragraphs(mk())
    translate.translate_paragraphs(mk())
    assert len(calls) == 1
