import threading
import time

from pytranslate import translate
from pytranslate.config import CONFIG


def _pars(n):
    return [{"text": f"Satz Nummer {i} ist hier", "par_rect": (0, 0, 1, 1), "line_rects": [(0, 0, 1, 1)]}
            for i in range(n)]


class SlowGoogle:
    def __init__(self, source, target):
        pass

    def translate(self, text):
        time.sleep(0.2)
        return "T:" + text


def test_google_parallel_fast_and_ordered(monkeypatch):
    monkeypatch.setattr(translate, "GoogleTranslator", SlowGoogle)
    monkeypatch.setattr(CONFIG, "offline", False)
    monkeypatch.setattr(CONFIG, "source_lang", "de")
    pars = _pars(8)
    t0 = time.monotonic()
    out = translate.translate_paragraphs(pars)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, elapsed
    assert [p["text"] for p in out] == [f"T:Satz Nummer {i} ist hier" for i in range(8)]


def test_google_uses_at_most_four_threads(monkeypatch):
    active, peak, lock = [0], [0], threading.Lock()

    class Probe(SlowGoogle):
        def translate(self, text):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.1)
            with lock:
                active[0] -= 1
            return text

    monkeypatch.setattr(translate, "GoogleTranslator", Probe)
    monkeypatch.setattr(CONFIG, "offline", False)
    monkeypatch.setattr(CONFIG, "source_lang", "de")
    translate.translate_paragraphs(_pars(12))
    assert 1 < peak[0] <= 4


def test_argos_path_is_sequential(monkeypatch):
    threads = set()

    def fake(text, src):
        threads.add(threading.get_ident())
        return "A:" + text

    monkeypatch.setattr(translate, "translate_text", fake)
    monkeypatch.setattr(CONFIG, "offline", True)
    monkeypatch.setattr(CONFIG, "source_lang", "de")
    out = translate.translate_paragraphs(_pars(5))
    assert threads == {threading.get_ident()}
    assert [p["text"][:2] for p in out] == ["A:"] * 5


def test_interruption_honoured_in_parallel_mode(monkeypatch):
    monkeypatch.setattr(translate, "GoogleTranslator", SlowGoogle)
    monkeypatch.setattr(CONFIG, "offline", False)
    monkeypatch.setattr(CONFIG, "source_lang", "de")
    t0 = time.monotonic()
    stop = lambda: time.monotonic() - t0 > 0.1
    report = translate.TranslationReport()
    out = translate.translate_paragraphs(_pars(40), should_stop=stop, report=report)
    assert time.monotonic() - t0 < 1.5            # 40 x 0.2 / 4 = 2 s if ignored
    untouched = [p for p in out if not p["text"].startswith("T:")]
    assert untouched and report.attempted < 40


def test_one_failure_in_parallel_keeps_others(monkeypatch):
    class Half(SlowGoogle):
        def translate(self, text):
            if "Nummer 1 " in text:
                raise RuntimeError("bad")
            return "T:" + text

    monkeypatch.setattr(translate, "GoogleTranslator", Half)
    monkeypatch.setattr(CONFIG, "offline", False)
    monkeypatch.setattr(CONFIG, "source_lang", "de")
    report = translate.TranslationReport()
    out = translate.translate_paragraphs(_pars(3), report=report)
    assert [p["text"].startswith("T:") for p in out] == [True, False, True]
    assert report.attempted == 3 and len(report.errors) == 1 and not report.all_failed
