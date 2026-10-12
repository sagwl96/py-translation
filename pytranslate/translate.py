"""Language detection and translation backends (Argos offline; Google only with --online)."""
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from .config import CONFIG

from . import mt

MODEL_MISSING_MSG = "Translation model not installed \u2014 run ./scripts/setup_models.sh"
ONLINE_MISSING_MSG = "--online needs the optional 'deep-translator' package; install with: uv sync --extra online"


class ModelMissingError(RuntimeError):
    """The offline translation model for a language pair is not installed."""


# deep-translator is an optional extra (uv sync --extra online) imported only for --online.
GoogleTranslator = None

_ARGOS_CACHE = {}   # (src, tgt) -> mt.Model or None (looked up once)

_TRANSLATION_CACHE = {}   # (src, tgt, text) -> translated text (successful results only)
_TRANSLATION_CACHE_MAX = 4096
_cache_lock = threading.Lock()
_argos_lock = threading.RLock()   # serialises model lookup/loading and translate calls
_warmup_thread = None


def clear_translation_cache():
    with _cache_lock:
        _TRANSLATION_CACHE.clear()

_DE_WORDS = frozenset("""
der die das den dem des ein eine einen einem einer und oder aber nicht ist sind war waren
wird werden wurde hat haben habe hatte ich du er sie es wir ihr mit von zu zum zur auf für
fuer bei nach aus über ueber auch noch nur wie was wer wo wann warum dass wenn dann schon
sehr mehr kein keine mein dein sein ihre im am vom beim guten morgen tag abend nacht hallo
danke bitte ja nein geht dir mir mich dich uns euch heute gut wir sich als bin bist seid
""".split())
_EN_WORDS = frozenset("""
the a an and or but not is are was were be been will would has have had i you he she it we
they me him her us them my your his its our their with from to of in on for at by as this
that these those what who where when why how if then so very more no yes also just can could
should do does did hello hi thanks please good morning today
""".split())


def detect_lang(text):
    """Tiny heuristic: return 'de' or 'en'. German if umlauts/ß or more German stop-words."""
    lowered = text.lower()
    if any(ch in lowered for ch in "äöüß"):
        return 'de'
    words = re.findall(r"[a-z']+", lowered)
    de = sum(1 for w in words if w in _DE_WORDS)
    en = sum(1 for w in words if w in _EN_WORDS)
    # Ties (incl. no stop-words, e.g. single-word signs) default to German, the app's primary source
    return 'en' if en > de else 'de'


class TranslationReport:
    """Filled by translate_paragraphs: how many paragraphs needed translating, and the failures."""

    def __init__(self):
        self.attempted = 0
        self.errors = []

    @property
    def all_failed(self):
        return self.attempted > 0 and len(self.errors) == self.attempted


_SKIPPED = object()
GOOGLE_MAX_WORKERS = 4


def _uses_google():
    return not CONFIG.offline


def check_online_available():
    """Raise RuntimeError with install instructions if --online cannot work."""
    try:
        _google_translator_class()
    except ImportError:
        raise RuntimeError(ONLINE_MISSING_MSG) from None


def _google_translator_class():
    global GoogleTranslator
    if GoogleTranslator is None:
        from deep_translator import GoogleTranslator as cls
        GoogleTranslator = cls
    return GoogleTranslator


def translate_paragraphs(paragraphs, should_stop=lambda: False, report=None):
    """Translate each paragraph's 'text' in place and return the list (order preserved).

    Online (Google) paragraphs are translated concurrently; Argos runs sequentially
    on its one loaded model. `should_stop()` is polled before each paragraph.
    """
    if report is None:
        report = TranslationReport()
    if not paragraphs:
        return paragraphs

    jobs = []   # (paragraph, src)
    for par in paragraphs:
        text = par['text']
        if not text:
            par['text'] = ""
            continue
        try:
            src = CONFIG.source_lang if CONFIG.source_lang != 'auto' else detect_lang(text)
        except Exception as e:
            print("Translation error:", e)
            continue
        if src == CONFIG.target_lang:
            continue  # already in the target language
        jobs.append((par, src))

    def run(job):
        par, src = job
        if should_stop():
            return _SKIPPED
        return translate_text(par['text'], src)

    def apply(job, outcome):
        par = job[0]
        if outcome is _SKIPPED:
            return
        report.attempted += 1
        if isinstance(outcome, Exception):
            print("Translation error:", outcome)
            report.errors.append(str(outcome) or type(outcome).__name__)
        else:
            par['text'] = outcome

    def safe(job):
        try:
            return run(job)
        except Exception as e:
            return e

    if not _uses_google():
        _prefill_cache_with_batches(jobs, should_stop)

    if _uses_google() and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=GOOGLE_MAX_WORKERS) as pool:
            outcomes = list(pool.map(safe, jobs))   # map preserves input order
        for job, outcome in zip(jobs, outcomes):
            apply(job, outcome)
    else:
        for job in jobs:
            if should_stop():
                break
            apply(job, safe(job))
    return paragraphs


def translate_text(text, src_lang='de'):
    """Translate `text`, memoised per (src, tgt, text) so repeat captures skip the backends."""
    key = (src_lang, CONFIG.target_lang, text)
    with _cache_lock:
        if key in _TRANSLATION_CACHE:
            return _TRANSLATION_CACHE[key]
    if CONFIG.offline:
        result = translate_argos(text, src_lang)
    else:
        result = translate_google(text, src_lang)
    _cache_put(key, result)
    return result


def _cache_put(key, result):
    with _cache_lock:
        if len(_TRANSLATION_CACHE) >= _TRANSLATION_CACHE_MAX:
            _TRANSLATION_CACHE.pop(next(iter(_TRANSLATION_CACHE)))   # drop oldest
        _TRANSLATION_CACHE[key] = result


def _prefill_cache_with_batches(jobs, should_stop):
    """Translate all uncached paragraphs of one source language in a single Argos batch
    and store them in the translation cache. Any problem is silently ignored: the
    per-paragraph path that follows then translates (and reports errors) as before."""
    by_src = {}
    for par, src in jobs:
        key = (src, CONFIG.target_lang, par['text'])
        with _cache_lock:
            cached = key in _TRANSLATION_CACHE
        if not cached and par['text'] not in by_src.setdefault(src, []):
            by_src[src].append(par['text'])
    for src, texts in by_src.items():
        if len(texts) < 2 or should_stop():
            continue
        try:
            outs = translate_argos_batch(texts, src)
        except Exception as e:
            print("Batch translation failed, translating one by one:", e)
            continue
        for text, out in zip(texts, outs or []):
            _cache_put((src, CONFIG.target_lang, text), out)


def translate_argos_batch(texts, src_lang):
    """Translate several texts with ONE ctranslate2 translate_batch call (all sentences of
    all texts together). Returns a list of results, or None if the model is not installed
    (callers then translate one by one and report the error)."""
    translation = get_argos_translation(src_lang, CONFIG.target_lang)
    if translation is None or not hasattr(translation, 'translate_many'):
        return None
    with _argos_lock:
        return translation.translate_many(texts, beam=max(1, CONFIG.beam))


def translate_argos(text, src_lang):
    """Translate offline. Raises (ModelMissingError, or whatever the model raised) on
    failure; there is deliberately no fallback to an online service."""
    translation = get_argos_translation(src_lang, CONFIG.target_lang)
    if translation is None:
        raise ModelMissingError(MODEL_MISSING_MSG)
    with _argos_lock:
        return translation.translate(text, beam=max(1, CONFIG.beam))


def _find_installed_argos(src, tgt):
    path = mt.find_model(src, tgt)
    return mt.Model(path) if path else None


def get_argos_translation(src, tgt, cache_miss=True):
    """Return a cached model object (translate / translate_many), or None. Looked up once
    per process.

    Serialised by a lock, so a first translate arriving during warm-up waits for it
    instead of loading the model a second time. With cache_miss=False a miss is not
    remembered (used by warm-up). Never touches the network.
    """
    with _argos_lock:
        return _get_argos_translation_locked(src, tgt, cache_miss)


def _get_argos_translation_locked(src, tgt, cache_miss):
    key = (src, tgt)
    if key in _ARGOS_CACHE:
        return _ARGOS_CACHE[key]
    translation = None
    try:
        translation = _find_installed_argos(src, tgt)
        if translation is None and not cache_miss:
            return None
    except Exception as e:
        print("Translation model unavailable:", e)
        translation = None
    _ARGOS_CACHE[key] = translation
    return translation


def warm_up_argos():
    """Load the Argos model for the expected source language and run one tiny translation.

    Safe to call from any thread.
    """
    src = CONFIG.source_lang if CONFIG.source_lang != 'auto' else 'de'
    translation = get_argos_translation(src, CONFIG.target_lang, cache_miss=False)
    if translation is not None:
        try:
            with _argos_lock:
                translation.translate("Hallo")   # the weights load lazily on first use
        except Exception as e:
            print("Argos warm-up failed:", e)


def start_warmup():
    """Start warm_up_argos() in a daemon thread, once. Returns the thread, or None if skipped
    (online mode or already started)."""
    global _warmup_thread
    if not CONFIG.offline or _warmup_thread is not None:
        return None
    _warmup_thread = threading.Thread(target=warm_up_argos, name="argos-warmup", daemon=True)
    _warmup_thread.start()
    return _warmup_thread


def translate_google(text, src_lang='auto'):
    translator = _google_translator_class()(source=src_lang, target=CONFIG.target_lang)
    return translator.translate(text)
