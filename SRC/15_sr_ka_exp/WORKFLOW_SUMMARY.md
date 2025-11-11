# Karnataka Budget Extraction Workflow

## Overview

Extracts Karnataka budget data from PDF using Gemini 2.5 Pro AI. Outputs two CSV types:
- **Minor Head Summary** (18 columns)
- **Detailed Expenditure Breakdown** (24 columns)

## How to Run

### 1. Setup (one-time)

```bash
# Install Python packages
pip install -r requirements.txt

# Install poppler
brew install poppler  # macOS
# OR
sudo apt-get install poppler-utils  # Ubuntu

# Create .env file with API key
echo "GEMINI_API_KEY=your_key_here" > .env
```

### 2. Configure Page Range

Edit [extract_workflow.py](extract_workflow.py) lines 50-51:

```python
START_PAGE = 176    # CHANGE: First page to extract
END_PAGE = 189      # CHANGE: Last page to extract
```

### 3. Run

```bash
python SRC/15_sr_ka_exp/extract_workflow.py
```

## Workflow

The workflow runs 5 steps automatically:

### Step 1: PDF → Images ([extract_workflow.py](extract_workflow.py#L89-L123))
- Converts pages `START_PAGE` to `END_PAGE` to JPG (300 DPI)
- **Output:** `OUT/15_sr_ka_exp/images/page_XXXX.jpg`

### Step 2: Gemini Extraction ([extract_workflow.py](extract_workflow.py#L366-L500))
- Sends each image to Gemini 2.5 Pro
- Uses previous page as context for state carry-forward
- Extracts 2 CSVs per page (Minor Head Summary + Detailed Breakdown)
- Pads codes with leading zeros (Major:4, Sub-Major:2, Minor:3, etc.)
- **Output:**
  - `OUT/15_sr_ka_exp/json_outputs/*.json`
  - `OUT/15_sr_ka_exp/csv_outputs/minor_head_summary/*.csv`
  - `OUT/15_sr_ka_exp/csv_outputs/detailed_expenditure_breakdown/*.csv`

### Step 3: CSV Cleaning ([csv_cleaner.py](csv_cleaner.py))
- Detects and fixes column misalignments
- Uses semantic understanding (Total/Header/Data rows)
- Validates code formats and row types
- **Output:** `OUT/15_sr_ka_exp/csv_cleaned/`

### Step 4: Error Logging ([extract_workflow.py](extract_workflow.py#L550-L623))
- Creates detailed error reports
- **Output:**
  - `OUT/15_sr_ka_exp/cleaning_logs/cleaning_log_YYYYMMDD_HHMMSS.json`
  - `OUT/15_sr_ka_exp/cleaning_logs/error_details_YYYYMMDD_HHMMSS.csv`

### Step 5: Combine CSVs ([csv_combine_validated.py](csv_combine_validated.py))
- Validates all cleaned CSVs
- Sorts by page number
- Combines with single header
- **Output:**
  - `OUT/15_sr_ka_exp/final_minor_head_summary.csv`
  - `OUT/15_sr_ka_exp/final_detailed_expenditure_breakdown.csv`

## Files

### Input Files
- **PDF:** `DATA/All_States/KA_2020-21/03-EXPVOL-01-1.pdf`
- **Prompt:** `PROMPTS/15_sr_ka_exp/sr_ka_prompt_csv_structure.md`
- **Environment:** `.env` (with `GEMINI_API_KEY`)

### Code Files
- [extract_workflow.py](extract_workflow.py) - Main workflow orchestrator
- [csv_cleaner.py](csv_cleaner.py) - Intelligent CSV alignment & validation
- [csv_combine_validated.py](csv_combine_validated.py) - Final CSV combination

### Output Files
- **Final CSVs:** `OUT/15_sr_ka_exp/final_*.csv` (2 files)
- **Logs:** `OUT/15_sr_ka_exp/cleaning_logs/` (JSON + CSV error reports)
- **Intermediate:** Images, JSONs, raw CSVs, cleaned CSVs (kept for debugging)

## Key Features

- **Smart Skip:** Already-processed pages are automatically skipped
- **Sequential Context:** Each page receives previous page's CSV as context
- **Error Auto-Fix:** Intelligently fixes column misalignments using semantic scoring
- **Comprehensive Logs:** Detailed error tracking with row-level reports
