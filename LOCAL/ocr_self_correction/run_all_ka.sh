#!/bin/bash
set -euo pipefail

# =============================================================================
# Karnataka Full Extraction: 8 years (2018-19 through 2026-27), 56 volumes
# =============================================================================
#
# Runs both year ranges with their respective prompts:
#   - 2018-19 to 2021-22: base_prompt.md (3 schemas: sub_major, minor, object)
#   - 2023-24 to 2026-27: base_prompt_newFYs.md (1 schema: object only)
#
# Usage:
#   ./run_all_ka.sh              # run everything (both ranges + validation)
#   ./run_all_ka.sh 18-22        # run only 2018-22
#   ./run_all_ka.sh 23-27        # run only 2023-27
#   ./run_all_ka.sh validate     # re-run validation on both
#
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

case "${1:-all}" in
  all)
    echo "================================================================"
    echo "  PHASE 1: Years 2018-19 through 2021-22 (old prompt, 3 schemas)"
    echo "================================================================"
    "$SCRIPT_DIR/run_18_22_ka.sh" all

    echo ""
    echo "================================================================"
    echo "  PHASE 2: Years 2023-24 through 2026-27 (new prompt, 1 schema)"
    echo "================================================================"
    "$SCRIPT_DIR/run_23_27_ka.sh" all

    echo ""
    echo "================================================================"
    echo "  ALL DONE"
    echo "================================================================"
    echo "  18-22 results: LOCAL/ocr_self_correction/outputs/runs/FULL_18_22/validation/"
    echo "  23-27 results: LOCAL/ocr_self_correction/outputs/runs/FULL_23_27/validation/"
    ;;
  18-22)
    "$SCRIPT_DIR/run_18_22_ka.sh" "${2:-all}"
    ;;
  23-27)
    "$SCRIPT_DIR/run_23_27_ka.sh" "${2:-all}"
    ;;
  validate)
    "$SCRIPT_DIR/run_18_22_ka.sh" validate
    "$SCRIPT_DIR/run_23_27_ka.sh" validate
    ;;
  *)
    echo "Usage: $0 [all|18-22|23-27|validate]"
    echo ""
    echo "  all        Run all 8 years with appropriate prompts (default)"
    echo "  18-22      Run 2018-19 through 2021-22 only"
    echo "  23-27      Run 2023-24 through 2026-27 only"
    echo "  validate   Re-run validation on both ranges"
    echo ""
    echo "  Pass a year to run a single year:"
    echo "    $0 18-22 2019-20"
    echo "    $0 23-27 2025-26"
    exit 1
    ;;
esac
