#!/bin/bash
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    interpreter=python3
    if command -v python3.13 >/dev/null 2>&1; then interpreter=python3.13; fi
    if "$interpreter" -c 'import PyQt5.QtWidgets' 2>/dev/null; then
        "$interpreter" -m venv --system-site-packages .venv
    else
        "$interpreter" -m venv .venv
    fi
fi
if ! .venv/bin/python -c 'import PyQt5.QtWidgets' 2>/dev/null; then
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python main.py
