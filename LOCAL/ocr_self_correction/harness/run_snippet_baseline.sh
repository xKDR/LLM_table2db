#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "${ROOT_DIR}"

# Source .env if it exists (dotenv also loaded in Python, this is belt-and-suspenders)
if [ -f LOCAL/ocr_self_correction/.env ]; then
    set -a
    source LOCAL/ocr_self_correction/.env
    set +a
fi

PYENV_VERSION=3.12.12/envs/py312demo \
python LOCAL/ocr_self_correction/harness/run_snippet_baseline.py "$@"
