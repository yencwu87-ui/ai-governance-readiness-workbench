#!/bin/bash
set -e
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
$PYTHON -m pip install -r requirements.txt
if command -v ollama >/dev/null 2>&1; then
  echo "Ollama detected. Models currently installed:"
  ollama list || true
fi
$PYTHON tools/build_control_testing_kb.py
$PYTHON -m pytest -q
$PYTHON -c 'import assessor, challenge, governance.knowledge_resolver; print("WB-047 import check: OK")'
exec $PYTHON -m streamlit run app.py
