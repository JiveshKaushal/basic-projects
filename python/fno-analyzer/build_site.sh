#!/usr/bin/env bash
# Builds the static GitHub Pages version of the dashboard into ./_site (or $1).
# The page runs the Python package in the browser with Pyodide.
set -euo pipefail
cd "$(dirname "$0")"
OUT="${1:-_site}"
rm -rf "$OUT"
mkdir -p "$OUT/py/fno_analyzer"
cp fno_analyzer/static/index.html "$OUT/index.html"
for f in __init__ api chain config futures insights presets pricing sample strategy; do
  cp "fno_analyzer/$f.py" "$OUT/py/fno_analyzer/"
done
cp data/sample_chain.csv "$OUT/sample_chain.csv"
touch "$OUT/.nojekyll"
echo "Built $OUT"
