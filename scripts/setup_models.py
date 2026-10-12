"""Install the offline models (see setup_models.sh). Python standard library only for the
download/extract logic; paths come from pytranslate.mt / pytranslate.ocr so the app finds
exactly what is installed here.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pytranslate import mt  # noqa: E402

INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata"
SRC, TGT = "de", "en"
# The Argos index gives no checksums; SHA-256 of packages we have verified by hand. A package
# not listed here is still checked (zip integrity + expected files), just not pinned.
KNOWN_SHA256 = {
    "translate-de_en-1_3": "becc2b0011f8249fcb89be9ecb75ba0d876b1fab93c28ee6ff0420936897d637",
}
USER_AGENT = "py-translation-setup/1"


def version_tuple(version):
    return tuple(int(p) if p.isdigit() else 0 for p in str(version).replace("_", ".").split("."))


def pick_package(index, src, tgt):
    """Newest index entry for src->tgt that has a download link, or None."""
    cands = [p for p in index if p.get("from_code") == src and p.get("to_code") == tgt and p.get("links")]
    return max(cands, key=lambda p: version_tuple(p.get("package_version", "0")), default=None)


def package_dirname(entry):
    return f"{entry['code']}-{str(entry['package_version']).replace('.', '_')}"


def fetch(url, dest, label):
    """Download url to dest (via dest.part), with a progress line on stderr. Returns sha256 hex."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest, done, shown = hashlib.sha256(), 0, 0
    tty = sys.stderr.isatty()
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest + ".part", "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if total and tty:
                print(f"\r  {label}: {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", file=sys.stderr, flush=True)
            elif total and done - shown >= 25e6:   # not a terminal: a line every 25 MB
                shown = done
                print(f"  {label}: {done / 1e6:.0f} / {total / 1e6:.0f} MB", file=sys.stderr, flush=True)
    if tty:
        print(file=sys.stderr)
    if total and done != total:
        os.remove(dest + ".part")
        raise RuntimeError(f"{label}: incomplete download ({done} of {total} bytes)")
    os.replace(dest + ".part", dest)
    return digest.hexdigest()


def safe_extract(archive, target):
    """Extract a zip, refusing members that would land outside `target`."""
    root = os.path.realpath(target)
    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"corrupt archive member: {bad}")
        for name in zf.namelist():
            if not os.path.realpath(os.path.join(root, name)).startswith(root + os.sep):
                raise RuntimeError(f"unsafe path in archive: {name}")
        zf.extractall(root)


def find_package_root(extracted):
    for dirpath, _dirs, files in os.walk(extracted):
        if "metadata.json" in files:
            return dirpath
    return None


def install_argos(models_dir, force=False):
    existing = mt.find_model(SRC, TGT)
    if existing and not force:
        print(f"Argos {SRC}->{TGT} model: already installed ({existing})")
        return
    print(f"Argos {SRC}->{TGT} model: looking up the package index ...")
    req = urllib.request.Request(INDEX_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        entry = pick_package(json.load(resp), SRC, TGT)
    if entry is None:
        raise RuntimeError(f"no {SRC}->{TGT} package in the Argos index")
    name = package_dirname(entry)
    os.makedirs(models_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=models_dir, prefix=".tmp-") as tmp:
        archive = os.path.join(tmp, name + ".argosmodel")
        digest = fetch(entry["links"][0], archive, name)
        want = KNOWN_SHA256.get(name)
        if want and digest != want:
            raise RuntimeError(f"{name}: SHA-256 mismatch (got {digest}, expected {want}); not installing")
        print(f"  sha256 {digest}" + (" (matches pinned value)" if want else " (no pinned value for this version)"))
        extracted = os.path.join(tmp, "x")
        safe_extract(archive, extracted)
        root = find_package_root(extracted)
        if root is None or not (os.path.isdir(os.path.join(root, "model"))
                                and os.path.isfile(os.path.join(root, "sentencepiece.model"))):
            raise RuntimeError(f"{name}: archive does not look like an Argos package")
        final = os.path.join(models_dir, name)
        if os.path.isdir(final):
            shutil.rmtree(final)
        shutil.move(root, final)
    print(f"Argos {SRC}->{TGT} model: installed in {final}")


def install_tessdata(tess_dir, langs, force=False):
    from pytranslate import ocr
    for lang in langs:
        if ocr.has_tessdata(lang) and not force:
            print(f"Tesseract '{lang}' data: already available ({ocr.find_tessdata(lang)})")
            continue
        os.makedirs(tess_dir, exist_ok=True)
        dest = os.path.join(tess_dir, f"{lang}.traineddata")
        fetch(TESSDATA_URL.format(lang=lang), dest, f"{lang}.traineddata")
        import tesserocr
        try:
            tesserocr.PyTessBaseAPI(path=tess_dir, lang=lang).End()
        except RuntimeError:
            os.remove(dest)
            raise RuntimeError(f"{lang}.traineddata downloaded but Tesseract cannot load it")
        print(f"Tesseract '{lang}' data: installed in {dest}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install the offline models for py-translation.")
    ap.add_argument("--eng", action="store_true", help="also fetch eng.traineddata (OCR of English text, --src en)")
    ap.add_argument("--force", action="store_true", help="download again even if already installed")
    args = ap.parse_args(argv)
    base = mt.app_data_dir()
    print(f"Model directory: {base}")
    try:
        install_argos(os.path.join(base, "models"), args.force)
        install_tessdata(os.path.join(base, "tessdata"), ["deu"] + (["eng"] if args.eng else []), args.force)
    except Exception as e:   # network down, disk full, bad archive ...
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    print("Done. Start the app with ./run.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
