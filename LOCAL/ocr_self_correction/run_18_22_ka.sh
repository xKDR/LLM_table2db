#!/bin/bash
set -euo pipefail

# =============================================================================
# Karnataka Full Extraction: 2018-19 through 2021-22 (28 volumes)
# =============================================================================
#
# What this does:
#   Extracts budget tables from PDF pages using Gemini, cleans/combines CSVs,
#   and runs validation checks (W01-W07, A01-A03).
#
# How it differs from the original run (SRC/15_sr_ka_exp/19_run_10years_KA.sh):
#   - Pipe-delimited extraction (fixes commas-in-descriptions breaking columns)
#   - Smart column alignment cleaner (fixes shifted financial columns)
#   - Keeps all rows (original dropped Has_Error=Yes rows)
#   - Integrated validation after extraction
#   - 3 schemas (sub_major, minor, object) instead of 5
#
# Prerequisites:
#   - pyenv with localenv-lsd environment
#   - GEMINI_API_KEY set in environment or in LOCAL/ocr_self_correction/.env
#   - poppler installed (brew install poppler)
#
# Usage:
#   ./run_18_22_ka.sh              # run everything
#   ./run_18_22_ka.sh 2019-20      # run just one year
#   ./run_18_22_ka.sh validate     # re-run validation only
#   ./run_18_22_ka.sh compare      # compare against production baseline
#
# =============================================================================

# --------------- Configuration (edit these) ---------------

MODEL="gemini-2.5-pro"              # gemini-2.5-pro | gemini-3-flash-preview | gemini-2.5-flash
WORKERS=4                           # parallel volumes (1=sequential, 7=all volumes in a year)
RUN_ID="FULL_18_22_April_03_2026"                 # identifies this run in metadata
FINANCIAL_YEARS="Accounts_2018_19,Budget_2019_20,Revised_2019_20,Budget_2020_21"

# Paths (relative to repo root)
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKSPACE="LOCAL/ocr_self_correction"
PROMPT="${WORKSPACE}/prompts/base_prompt.md"
OUT_ROOT="${WORKSPACE}/outputs/runs/${RUN_ID}"
MANIFEST="${WORKSPACE}/manifests/full_18_22_manifest.csv"
HARNESS="${WORKSPACE}/harness/run_snippet_baseline.py"
VALIDATION="${WORKSPACE}/harness/run_validation.py"
COMPARE="${WORKSPACE}/harness/compare_runs.py"

PYTHON=$(which python)
# If empty, force this value:
# Python — adjust if your setup differs
PYTHON=${PYTHON:-"$HOME/.pyenv/versions/localenv-lsd/bin/python"}
# --------------- End configuration ---------------

cd "$REPO_ROOT"

# Check prerequisites
if [ ! -f "$PROMPT" ]; then
  echo "ERROR: Prompt not found: $PROMPT"
  exit 1
fi
if ! $PYTHON -m test >> /dev/null; then
  echo "ERROR: Python not found, or errors running it: $PYTHON"
  echo "  Adjust the PYTHON variable at the top of this script."
  exit 1
fi
if ! command -v pdftoppm &>/dev/null; then
  echo "ERROR: poppler not installed. Run: brew install poppler"
  exit 1
fi

# --------------- Functions ---------------

run_year() {
  local year="$1"
  echo "================================================================"
  echo "  Extracting: ${year} (model=${MODEL}, workers=${WORKERS})"
  echo "================================================================"

  # Create a temp manifest for just this year
  local tmp_manifest
  tmp_manifest=$(mktemp)
  head -1 "$MANIFEST" > "$tmp_manifest"
  grep "^${year}," "$MANIFEST" >> "$tmp_manifest"

  local count
  count=$(tail -n +2 "$tmp_manifest" | wc -l | tr -d ' ')
  echo "  Volumes: ${count}"

  "$PYTHON" "$HARNESS" \
    --manifest "$tmp_manifest" \
    --prompt-path "$PROMPT" \
    --out-root "$OUT_ROOT" \
    --model "$MODEL" \
    --financial-years "$FINANCIAL_YEARS" \
    --run-id "$RUN_ID" \
    --workers "$WORKERS" \
    --skip-validation

  rm -f "$tmp_manifest"
  echo "  Done: ${year}"
}

run_validation() {
  echo "================================================================"
  echo "  Running validation"
  echo "================================================================"
  "$PYTHON" "$VALIDATION" \
    --input-base "$OUT_ROOT" \
    --output-base "${OUT_ROOT}/validation"
  echo "  Report: ${OUT_ROOT}/validation/validation_report.md"
}

run_compare() {
  local baseline="${WORKSPACE}/outputs/runs/PROD_4Y_BASELINE/validation/validation_summary.csv"

  # Generate baseline from production data if it doesn't exist
  if [ ! -f "$baseline" ]; then
    echo "  Generating production baseline validation..."
    "$PYTHON" "$VALIDATION" \
      --input-base "OUT/25_run_10years_KA_timing" \
      --output-base "${WORKSPACE}/outputs/runs/PROD_4Y_BASELINE/validation"
  fi

  echo "================================================================"
  echo "  Comparing against production baseline"
  echo "================================================================"
  "$PYTHON" "$COMPARE" \
    --run-a "$baseline" \
    --run-b "${OUT_ROOT}/validation/validation_summary.csv" \
    --label-a PROD --label-b "$RUN_ID"
}

# --------------- Main ---------------

case "${1:-all}" in
  all)
    run_year "2018-19"
    run_year "2019-20"
    run_year "2020-21"
    run_year "2021-22"
    run_validation
    ;;
  validate)
    run_validation
    ;;
  compare)
    run_compare
    ;;
  201[89]-*|202[012]-*)
    run_year "$1"
    echo ""
    echo "  To validate after all years are done: $0 validate"
    ;;
  *)
    echo "Usage: $0 [all|validate|compare|YEAR]"
    echo ""
    echo "  all        Run all 4 years then validate (default)"
    echo "  validate   Re-run validation on existing output"
    echo "  compare    Compare against OUT/25_run_10years_KA_timing"
    echo "  YEAR       Run a single year (e.g., 2019-20)"
    exit 1
    ;;
esac
