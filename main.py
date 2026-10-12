#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thin entry point: `python main.py` == `python -m pytranslate`."""
import sys

from pytranslate.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
