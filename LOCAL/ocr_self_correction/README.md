# OCR Self-Correction

A closed-loop system for improving Karnataka budget extraction quality through validation-driven pipeline fixes and prompt tuning.

## What this does

Extracts structured budget data from Karnataka expenditure PDF pages using Gemini, validates the output against internal consistency checks (do the object-level rows sum to the minor-head totals?), and uses the validation failures to drive targeted fixes — first in the downstream pipeline, then in the prompt.

## What we found

We ran 8 extraction experiments (R0-R5, B1-B3) on 28 pages across 6 budget volumes. See `run_log.md` for the full iteration history and `run_r1_r5_summary.md` for the condensed results.

**The pipeline was the first bottleneck.** When we switched to pipe-delimited output, the CSV cleaner was padding missing fields at the wrong position, shifting financial columns. Fixing this single issue took weighted accuracy from 19.5% to 82.3%.

**The prompt was the second bottleneck.** The LLM was leaving `Sub_Major_Head_Code` empty and emitting duplicate total rows. Two targeted prompt patches brought accuracy from 82.3% to 93.2%.

**The model is the remaining bottleneck.** We benchmarked four Gemini models on the same prompt and pipeline:

| Model | Weighted Accuracy | Cost per page |
|-------|-------------------|---------------|
| gemini-3.1-flash-lite-preview | 92.6% | $0.005 |
| gemini-3-flash-preview | 94.8% | $0.079 |
| gemini-2.5-pro | 95.1% | $0.102 |
| gemini-3.1-pro-preview | **95.8%** | $0.153 |

## Directory structure

```
LOCAL/ocr_self_correction/
├── harness/
├── pipeline/
├── prompts/
├── manifests/
├── snippets/
├── outputs/
├── reports/
├── run_log.md
├── run_r1_r5_summary.md
├── llm_benchmark_assessment.md
└── README.md
```

**harness/** — Scripts that orchestrate the end-to-end flow. `run_snippet_baseline.py` is the main entry point: it takes a manifest of snippets, runs extraction -> pipe-to-comma conversion -> cleaning -> combining -> validation for each volume, optionally in parallel. `run_validation.py` runs the 10 consistency checks (W01-W07 within-schema, A01-A03 across-schema). `compare_runs.py` produces a markdown delta report between any two runs.

**pipeline/** — The extraction and post-processing code, forked from `SRC/23_ka_validation_fix/` with fixes applied. `extract_workflow.py` handles PDF-to-image conversion and Gemini API calls. `csv_cleaner.py` aligns columns (smart insertion using Row_Type/Row_Level anchors, hierarchy pair detection for single-field gaps), normalises codes, infers row types. `csv_combine_validated.py` merges per-page CSVs into final summaries without dropping rows. `schemas.py` defines the column schemas for all 5 budget hierarchy levels.

**prompts/** — The extraction prompt sent to Gemini. `base_prompt.md` is the current version (pipe-delimited output, field-count enforcement with examples, Sub_Major_Head_Code rules, total-row uniqueness). `base_prompt_newFYs.md` is the variant for 2023-24+ financial years.

**manifests/** — CSV files listing which PDF snippets to extract. Each row specifies a volume, page range, and source PDF path. The harness reads this to know what to process.

**snippets/** — The source PDF files for the test set. 6 volumes, 28 pages total, selected to cover the main validation hotspots (W01/A01 failures, W02/A02 primary volumes).

**outputs/** — All run outputs, organised by run ID (`R0`-`R5`, `B1`-`B3`). Each run contains per-volume directories with images, JSON extraction, raw CSVs, cleaned CSVs, final combined CSVs, cleaning logs, and cost tracking. The `validation/` subdirectory holds the validation summary and per-volume detail CSVs.

**reports/** — Analysis documents from the baseline setup phase.

## Validation checks

| Check | Type | What it validates |
|-------|------|-------------------|
| W01 | in-schema | Object-Head Data sums to Minor-Head Total (within object_head) |
| W02 | in-schema | Object-Head Data sums to Sub-Major-Head Total (within object_head) |
| W03 | in-schema | Minor-Head Data sums to Minor-Head Total (within minor_head) |
| W04 | in-schema | Minor-Head Data sums to Sub-Major-Head Total (within minor_head) |
| W05 | in-schema | Sub-Major-Head Data sums to Sub-Major-Head Total (within sub_major_head) |
| W06 | in-schema | Object-Head Data sums to Detailed-Head Total / HOA Total (within object_head) |
| W07 | in-schema | Object-Head Data sums to Major-Head Total (within object_head) |
| A01 | across-schema | Object-Head Minor Total matches Minor-Head Data |
| A02 | across-schema | Object-Head Sub-Major Total matches Sub-Major-Head Data |
| A03 | across-schema | Minor-Head Sub-Major Total matches Sub-Major-Head Data |

Checks with 0 comparable keys are omitted from reporting. See `OUT/27_KA_SR_run_minor/27_validation_methodology.md` for the full methodology.

## Running a benchmark

```bash
# Set API key
source LOCAL/ocr_self_correction/.env

# Run on a model
$HOME/.pyenv/versions/py312demo/bin/python \
  LOCAL/ocr_self_correction/harness/run_snippet_baseline.py \
  --run-id test1 \
  --out-root LOCAL/ocr_self_correction/outputs/runs/test1 \
  --model gemini-3-flash-preview

# Compare against baseline
$HOME/.pyenv/versions/py312demo/bin/python \
  LOCAL/ocr_self_correction/harness/compare_runs.py \
  --run-a LOCAL/ocr_self_correction/outputs/runs/R0/validation/validation_summary.csv \
  --run-b LOCAL/ocr_self_correction/outputs/runs/test1/validation/validation_summary.csv \
  --label-a R0 --label-b test1
```
