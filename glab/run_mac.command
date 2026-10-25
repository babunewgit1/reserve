#!/bin/bash
# ScriptReel Studio launcher for macOS
cd "$(dirname "$0")"

if [ -f ".venv/bin/python" ]; then
    exec .venv/bin/python -m scriptreel "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 -m scriptreel "$@"
else
    echo "Error: Python environment (.venv) not found."
    read -p "Press enter to exit..."
    exit 1
fi
