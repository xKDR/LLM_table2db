#!/bin/bash
set -euo pipefail

# =============================================================================
# Karnataka Full Extraction: 2023-24 through 2026-27 (28 volumes)
# =============================================================================
#
# Uses the new-FY prompt (base_prompt_newFYs.md) which extracts only
# object_head_summary_csv. These years have a different document structure:
#   - HOA Total (Detailed-Head level) instead of Minor-Head totals
#   - Major-Head Total as "XXXX - Total:"
#   - Only object_head schema (no minor_head or sub_major_head)
#
# Validation checks: W06 (Object→HOA Total), W07 (Object→Major Total)
#
# Prerequisites:
#   - pyenv with localenv-lsd environment
#   - GEMINI_API_KEY set in environment or in LOCAL/ocr_self_correction/.env
#   - poppler installed (brew install poppler)
#
# Usage:
#   ./run_23_27_ka.sh              # run everything
#   ./run_23_27_ka.sh 2024-25      # run just one year
#   ./run_23_27_ka.sh validate     # re-run validation only
#
# =============================================================================

# --------------- Configuration (edit these) ---------------

MODEL="gemini-3-flash-preview"      # gemini-2.5-pro | gemini-3-flash-preview | gemini-2.5-flash
WORKERS=4                           # parallel volumes (1=sequential, 7=all volumes in a year)
RUN_ID="FULL_23_27"                 # identifies this run in metadata
FINANCIAL_YEARS="Financial_Col_1,Financial_Col_2,Financial_Col_3,Financial_Col_4"

# Paths (relative to repo root)
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKSPACE="LOCAL/ocr_self_correction"
PROMPT="${WORKSPACE}/prompts/base_prompt_newFYs.md"
OUT_ROOT="${WORKSPACE}/outputs/runs/${RUN_ID}"
MANIFEST="${WORKSPACE}/manifests/full_23_27_manifest.csv"
HARNESS="${WORKSPACE}/harness/run_snippet_baseline.py"
VALIDATION="${WORKSPACE}/harness/run_validation.py"

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

# --------------- Main ---------------

case "${1:-all}" in
  all)
    run_year "2023-24"
    run_year "2024-25"
    run_year "2025-26"
    run_year "2026-27"
    run_validation
    ;;
  validate)
    run_validation
    ;;
  202[3456]-*)
    run_year "$1"
    echo ""
    echo "  To validate after all years are done: $0 validate"
    ;;
  *)
    echo "Usage: $0 [all|validate|YEAR]"
    echo ""
    echo "  all        Run all 4 years then validate (default)"
    echo "  validate   Re-run validation on existing output"
    echo "  YEAR       Run a single year (e.g., 2024-25)"
    exit 1
    ;;
esac
