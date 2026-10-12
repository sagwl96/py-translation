"""Offline machine translation straight from an Argos Translate model package.

An Argos package directory holds ``model/`` (a CTranslate2 model), ``sentencepiece.model`` and
``metadata.json`` (a ``stanza/`` or ``minisbd/`` folder, if present, is ignored). We run it with
``ctranslate2`` + ``sentencepiece`` only, exactly as argostranslate 1.11 did: split into
paragraphs at newlines and into sentences, SentencePiece-encode each sentence to pieces, translate
all of them in one batch, concatenate the pieces of a paragraph and decode them.

Model packages are installed by ``scripts/setup_models.sh`` into
``$XDG_DATA_HOME/py-translation/models/``; an existing argos-translate install is reused.
"""
import glob
import json
import os
import re

MAX_BATCH_TOKENS = 1024
LENGTH_PENALTY = 0.2


# --------------------------------------------------------------------------- locations

def data_home():
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def app_data_dir():
    """Where setup_models.sh keeps models and tessdata."""
    return os.path.join(data_home(), "py-translation")


def model_search_dirs():
    dirs = [os.path.join(app_data_dir(), "models")]
    if not os.environ.get("PYTRANSLATE_NO_LEGACY_PATHS"):
        dirs.append(os.path.join(data_home(), "argos-translate", "packages"))
    return dirs


def _version_key(path):
    nums = re.findall(r"\d+", os.path.basename(path).split("-")[-1])
    return tuple(int(n) for n in nums)


def _is_package(path):
    return (os.path.isdir(os.path.join(path, "model"))
            and os.path.isfile(os.path.join(path, "sentencepiece.model")))


def find_model(src, tgt):
    """Newest installed ``translate-<src>_<tgt>-*`` package directory, or None."""
    for base in model_search_dirs():
        found = sorted((p for p in glob.glob(os.path.join(glob.escape(base), f"translate-{src}_{tgt}-*"))
                        if _is_package(p)), key=_version_key, reverse=True)
        if found:
            return found[0]
    return None


# --------------------------------------------------------------------------- sentence splitting

_ABBREVIATIONS = frozenset("""
z.b. d.h. u.a. u.u. o.ä. i.d.r. s.o. s.u. v.a. u.v.m. z.t. z.zt. m.e. n.chr. v.chr. e.v. e.g. i.e. a.m. p.m.
usw. bzw. ca. nr. str. dr. hr. fr. hbf. inkl. ggf. evtl. vgl. prof. tel. abb. std. min. sek. mio. mrd. etc.
sog. zzgl. exkl. max. mind. gem. geb. gest. bes. bzgl. betr. ggfs. kfz. pkw. lkw. mwst. ust. gmbh. co. ev. kath.
mo. di. mi. do. sa. so. jan. feb. mär. apr. jun. jul. aug. sep. sept. okt. nov. dez.
mr. mrs. ms. jr. sr. st. vs. inc. ltd. no. vol. fig. approx. dept. sec.
""".split())
_MONTHS = frozenset("""
januar februar märz april mai juni juli august september oktober november dezember
january february march june july october december
""".split())
_ORDINAL_PREFIX = frozenset("""
am den dem der des vom bis zum zur ab seit im ins um vor nach zwischen ersten
""".split())

# words that typically start a sentence: after "<small number>." they mean the number ended one
_STARTERS = frozenset("""
der die das den dem des ein eine einen einem einer es er sie wir ich ihr man und aber auch dann doch so da hier
dies diese dieser dieses in im am an auf aus bei mit nach von vor zu zum zur für um wenn als wie was wer wo
the a an it he she we they i this that there these in on at if and but so then
""".split())

# end punctuation (+ closing quotes/brackets), whitespace, then a capital letter, digit or opening quote
_BOUNDARY = re.compile(r"""([.!?\u2026]+["'\u201d\u201c\u2019\u00bb)\]]*)(\s+)(?=["'\u201e\u201c\u00bb\u00ab(\[\u00bf\u00a1]*(\w))""")


def _is_abbreviation(word, next_word):
    """True if the '.' ending `word` is part of an abbreviation/ordinal, not a sentence end."""
    word = word.lstrip("\"'„“»«([")
    low = word.lower()
    if low in _ABBREVIATIONS or low.endswith("str."):    # "Hauptstr. 5"
        return True
    core = low[:-1]
    if len(core) == 1 and core.isalpha():
        return True                                  # initial: "J. Schmidt", "z. B."
    if "." in core and all(len(p) <= 2 for p in core.split(".")):
        return True                                  # "u.a.", "d.h.", "i.d.R."
    if core.isdigit() and len(core) <= 2 and next_word.lower() in _MONTHS:
        return True                                  # "am 08. Oktober"
    return False


def split_sentences(text):
    """Split one paragraph (no newlines) into stripped sentences. Heuristic, for de/en."""
    text = text.strip()
    if not text:
        return []
    sentences, start = [], 0
    for m in _BOUNDARY.finditer(text):
        if m.group(3).islower():
            continue                                  # "...", then a lowercase word: same sentence
        punct = m.group(1)
        if punct.rstrip("\"'”’»)]") == ".":
            words = text[start:m.end(1)].split()
            word = re.sub(r"[\"'”’»)\]]+$", "", words[-1]) if words else ""
            nxt = re.match(r"\w+", text[m.end():])
            nxt = nxt.group(0) if nxt else ""
            if _is_abbreviation(word, nxt):
                continue
            num = word.lstrip("\"'\u201e\u201c\u00bb\u00ab([")
            if (num[:-1].isdigit() and len(num) <= 3 and not nxt.isdigit()
                    and (len(words) == 1 or words[-2].lower() in _ORDINAL_PREFIX
                         or nxt.lower() not in _STARTERS)):
                continue          # "den 3. Oktober", "der 2. Weltkrieg", list item "1. Renaissance"
        sentences.append(text[start:m.end(1)])
        start = m.end()
    sentences.append(text[start:])
    return [s.strip() for s in sentences if s.strip()]


# --------------------------------------------------------------------------- model

class Model:
    """One translation direction loaded from an Argos package directory (loaded lazily)."""

    def __init__(self, package_dir):
        self.package_dir = package_dir
        with open(os.path.join(package_dir, "metadata.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.from_code = meta.get("from_code", "")
        self.to_code = meta.get("to_code", "")
        self.target_prefix = meta.get("target_prefix", "")
        self._translator = None
        self._sp = None

    def __repr__(self):
        return f"<mt.Model {self.from_code}->{self.to_code} {self.package_dir}>"

    def load(self):
        """Create the CTranslate2 translator and SentencePiece processor (idempotent)."""
        if self._translator is None:
            import ctranslate2
            import sentencepiece
            self._sp = sentencepiece.SentencePieceProcessor(
                model_file=os.path.join(self.package_dir, "sentencepiece.model"))
            self._translator = ctranslate2.Translator(
                os.path.join(self.package_dir, "model"), device="cpu",
                inter_threads=1, intra_threads=0, compute_type="auto")
        return self

    @property
    def translator(self):
        return self.load()._translator

    def _decode(self, tokens):
        # decode_pieces, then argostranslate's extra '_' -> ' ' replacement, kept for identical output
        text = self._sp.decode_pieces(tokens).replace("▁", " ").replace("_", " ")
        if self.target_prefix and text.startswith(self.target_prefix):
            text = text[len(self.target_prefix):]
        return text[1:] if text[:1] == " " else text

    def translate_many(self, texts, beam=2):
        """Translate several texts with ONE translate_batch call over all their sentences."""
        self.load()
        flat, counts = [], []        # tokenised sentences; per text: sentences per paragraph
        for text in texts:
            per_par = []
            for para in text.split("\n"):
                sentences = split_sentences(para)
                flat.extend(self._sp.encode(s, out_type=str) for s in sentences)
                per_par.append(len(sentences))
            counts.append(per_par)
        results = []
        if flat:
            prefix = [[self.target_prefix]] * len(flat) if self.target_prefix else None
            results = self._translator.translate_batch(
                flat, target_prefix=prefix, replace_unknowns=True,
                max_batch_size=MAX_BATCH_TOKENS, batch_type="tokens",
                beam_size=max(1, beam), num_hypotheses=1, length_penalty=LENGTH_PENALTY)
        outputs, pos = [], 0
        for per_par in counts:
            value = ""
            for n in per_par:
                tokens = []
                for r in results[pos:pos + n]:
                    tokens.extend(r.hypotheses[0])
                pos += n
                value = "\n".join([value, self._decode(tokens)])
            outputs.append(value.lstrip("\n"))
        return outputs

    def translate(self, text, beam=2):
        return self.translate_many([text], beam)[0]
