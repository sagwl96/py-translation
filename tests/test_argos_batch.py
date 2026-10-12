"""P8.6: one translate_batch call per capture, beam from config."""
import pytest

from pytranslate import translate
from pytranslate.config import CONFIG

TEXTS = ["Guten Morgen, wie geht es Ihnen heute? Das Wetter ist sehr schön.",
         "Die Kinder spielen im Garten.",
         "Wir gehen später in den Park spazieren und trinken einen Kaffee."]


@pytest.fixture
def argos(monkeypatch):
    monkeypatch.setattr(CONFIG, "offline", True)
    monkeypatch.setattr(CONFIG, "source_lang", "de")
    monkeypatch.setattr(CONFIG, "target_lang", "en")
    tr = translate.get_argos_translation("de", "en")
    if tr is None:
        pytest.skip("de->en Argos model not installed")
    return tr


def test_batch_matches_one_by_one(argos):
    batch = translate.translate_argos_batch(TEXTS, "de")
    single = [argos.translate(t, beam=CONFIG.beam) for t in TEXTS]
    assert batch == single
    assert "weather is very nice" in batch[0]


def test_multiline_text_keeps_paragraphs(argos):
    out = argos.translate("Guten Morgen.\nDie Kinder spielen im Garten.", beam=2)
    assert out.count("\n") == 1 and "garden" in out.split("\n")[1]


def test_translate_paragraphs_uses_one_batch_call(argos, monkeypatch):
    translate.translate_argos_batch(TEXTS[:2], "de")   # make sure the translator exists
    calls, batch_caps = [], []
    real = argos.translator

    class Spy:
        def translate_batch(self, *a, **k):
            calls.append(k.get("beam_size"))
            batch_caps.append(k.get("max_batch_size"))
            return real.translate_batch(*a, **k)
    monkeypatch.setattr(argos, "_translator", Spy())
    pars = [{"text": t} for t in TEXTS]
    out = translate.translate_paragraphs(pars)
    assert len(calls) == 1 and calls == [CONFIG.beam]
    # a small token cap would split captures into many tiny batches (~2x slower)
    assert batch_caps[0] >= 256
    assert all(p["text"] and p["text"] != t for p, t in zip(out, TEXTS))
    assert "play in the garden" in out[1]["text"].lower()


def test_batch_failure_falls_back_to_per_paragraph(argos, monkeypatch):
    monkeypatch.setattr(translate, "translate_argos_batch",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = translate.translate_paragraphs([{"text": t} for t in TEXTS])
    assert "play in the garden" in out[1]["text"].lower()
