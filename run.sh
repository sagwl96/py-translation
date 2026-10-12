#!/bin/bash
# Run the app in the uv-managed environment (create it first with: uv sync).
cd "$(dirname "$0")"
exec uv run --frozen pytranslate "$@"
