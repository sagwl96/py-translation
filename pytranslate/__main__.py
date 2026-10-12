import argparse
import sys

from .config import CONFIG, Config, apply_config


def build_parser():
    p = argparse.ArgumentParser(
        prog="pytranslate", allow_abbrev=False,
        description="Instant screen translator: press Space to OCR and translate the area under the window.")
    p.add_argument("--src", default="auto", metavar="LANG",
                   help="source language code, or 'auto' to detect per paragraph (default: auto)")
    p.add_argument("--tgt", default="en", metavar="LANG",
                   help="target language code (default: en)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--online", dest="offline", action="store_false",
                      help="use Google Translate instead (sends the recognised text to Google; "
                           "needs network and the optional extra: uv sync --extra online)")
    mode.add_argument("--offline", dest="offline", action="store_true",
                      help="translate fully offline with the local Argos model (default)")
    p.set_defaults(offline=True)
    p.add_argument("--min-conf", type=int, default=Config.min_ocr_conf, metavar="N",
                   help="drop OCR words with confidence below N, 0-100 (default: %(default)s)")
    p.add_argument("--ocr-lang", default="", metavar="LANGS",
                   help="Tesseract language(s), e.g. deu or eng+deu (default: deu, or eng with --src en)")
    p.add_argument("--beam", type=int, default=Config.beam, metavar="N",
                   help="Argos beam size, 1-8; higher is slower (default: %(default)s)")
    p.add_argument("--on-top", action="store_true",
                   help="start with the window always on top (toggle with T)")
    p.add_argument("--save-captures", default="", metavar="DIR",
                   help="save every capture as DIR/<timestamp>.png plus a .json with the OCR lines, "
                        "paragraphs, translations, settings and dpr (to report/replay failing captures)")
    return p


def config_from_args(argv=None):
    """Parse command-line arguments (without the program name) into a new Config."""
    args = build_parser().parse_args(argv)
    return Config(source_lang=args.src, target_lang=args.tgt, offline=args.offline, min_ocr_conf=args.min_conf,
                  ocr_lang=args.ocr_lang, beam=max(1, args.beam), on_top=args.on_top,
                  save_captures=args.save_captures)


def main(argv=None):
    # Parse before creating QApplication so --help / bad flags never open a window.
    argv = sys.argv if argv is None else argv
    apply_config(config_from_args(argv[1:]))
    if not CONFIG.offline:
        from . import translate
        try:
            translate.check_online_available()
        except RuntimeError as e:
            print("error:", e, file=sys.stderr)
            return 2

    from PyQt6 import QtWidgets
    from .ui import MainWindow
    from .icons import make_app_icon
    app = QtWidgets.QApplication(argv[:1])
    app.setWindowIcon(make_app_icon())
    window = MainWindow()
    window.show()
    from . import translate
    translate.start_warmup()   # background, non-blocking; no-op in --online mode
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
