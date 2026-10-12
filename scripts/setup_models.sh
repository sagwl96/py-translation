#!/bin/bash
# Download the offline models into ${XDG_DATA_HOME:-~/.local/share}/py-translation/ (idempotent):
#   - the Argos Translate de->en package (~150 MB), unless one is already installed
#   - Tesseract German data deu.traineddata (tessdata_fast, ~1.5 MB), unless found on the system
# Options: --eng (also fetch eng.traineddata)   --force (download again)
# Needs no apt/sudo. Run `uv sync` first.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run --frozen python scripts/setup_models.py "$@"
