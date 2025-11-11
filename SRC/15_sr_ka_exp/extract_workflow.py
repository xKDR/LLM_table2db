#!/usr/bin/env python3
"""
Karnataka Budget Extraction Workflow
=====================================
This script performs a complete end-to-end extraction workflow:
1. Extracts pages 14-49 from the source PDF
2. Converts pages to JPG images
3. Processes each image using Gemini AI with sequential context
4. Saves raw JSON responses from Gemini
5. Normalizes code fields (keeps/pads leading zeros, sets default Row_Type)
6. Combines all CSV outputs into separate files by archetype
"""

import argparse
import json
import os
import re
import sys

from pathlib import Path

# Third-party imports
try:
    from google import genai
    from google.genai import types
    from PIL import Image
    from dotenv import load_dotenv
    from pdf2image import convert_from_path
except ImportError as e:
    print(f"ERROR: Missing required package: {e}")
    print("\nPlease install required packages:")
    print("  pip install google-genai pillow python-dotenv pdf2image")
    print("\nAlso install poppler (required for pdf2image):")
    print("  macOS: brew install poppler")
    print("  Ubuntu/Debian: sudo apt-get install poppler-utils")
    sys.exit(1)

# Import shared schemas
from schemas import (
    SUB_MAJOR_HEAD_SCHEMA,
    MINOR_HEAD_SCHEMA,
    SUB_HEAD_SCHEMA,
    DETAILED_HEAD_SCHEMA,
    OBJECT_HEAD_SCHEMA
)

# Load environment variables
load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

# Paths
API_KEY = os.getenv("GEMINI_API_KEY")

# All other configuration has moved to the argparse section in main()

# ============================================================================
# STEP 1: PDF to Images
# ============================================================================

def extract_pdf_to_images(config):
    """Convert the provided PDF into a set of image files

    This goes from start-end page, and turns the PDF into a set of jpg
    files for subsequent prompting with the LLM.

    Images are better since they are
    1. Smaller
    2. Remove bad font encoding metadata
    """
    print("=" * 80)
    print("STEP 1: Extracting PDF pages to images")
    print("=" * 80)

    if not config['PDF_PATH'].exists():
        print(f"ERROR: PDF not found at {config['PDF_PATH']}")
        sys.exit(1)

    config['IMAGES_DIR'].mkdir(parents=True, exist_ok=True)

    print(f"Source PDF: {config['PDF_PATH']}")
    print(f"Extracting pages {config['START_PAGE']}-{config['END_PAGE']}")
    print(f"Output directory: {config['IMAGES_DIR']}")

    try:
        images = convert_from_path(
            str(config['PDF_PATH']),
            first_page=config['START_PAGE'],
            last_page=config['END_PAGE'],
            dpi=300,
            fmt="jpeg"
        )
        for i, image in enumerate(images, start=config['START_PAGE']):
            output_path = config['IMAGES_DIR'] / f"page_{i:04d}.jpg"
            image.save(output_path, "JPEG", quality=95)
            print(f"  Saved: {output_path.name}")

        print(f"\n✅ Successfully extracted {len(images)} pages")
        return len(images)

    except Exception as e:
        print(f"ERROR during PDF extraction: {e}")
        sys.exit(1)

# ============================================================================
# Utilities: CSV helpers (preserve/pad codes; set defaults)
# ============================================================================

def read_prompt_text(config):
    """Return the prompt as a string from the file in the config"""
    try:
        with open(config['PROMPT_FILE'], "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"ERROR reading prompt file at {config['PROMPT_FILE']}: {e}")
        sys.exit(1)

def fix_csv_formatting(csv_text: str) -> str:
    """
    Re-writes CSV with safe quoting WITHOUT coercing code strings to numbers.
    """
    import csv
    from io import StringIO
    try:
        reader = csv.reader(StringIO(csv_text))
        rows = list(reader)
        out = StringIO()
        writer = csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        for row in rows:
            writer.writerow(row)
        return out.getvalue().strip()
    except Exception as e:
        print(f"    ⚠️  CSV formatting fix failed: {e}, using original output")
        return csv_text

def _pad(code: str, width: int) -> str:
    """Pad code with leading zeros to specified width."""
    if code is None:
        return ""
    s = str(code).strip()
    if s == "" or s == "...":
        return ""
    # Remove any non-digits that may creep in
    digits = re.sub(r"[^\d]", "", s)
    if digits == "":
        return s  # fallback
    return digits.zfill(width)

def normalize_detailed_csv(csv_text: str) -> str:
    """
    Schema-aware pass for detailed_csv that:
      - Keeps codes as strings (no ints)
      - Pads Major_Head_Code to 4, Sub_Major_Head_Code to 2
      - Pads Minor_Head_Code to 3, Sub_Head_Code to 1, Detailed_Head_Code to 2
      - Pads Object_Head_Code to 3 (only for Object-Head rows)
      - Sets Row_Type based on rules: Total if description has "Total",
        Header if all financial columns empty, Data if has financial values
    """
    import csv
    from io import StringIO

    if not csv_text.strip():
        return csv_text

    reader = csv.reader(StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return csv_text

    header = rows[0]
    idx = {name: i for i, name in enumerate(header)}

    # Required columns indices (guard if missing)
    mhcode = idx.get("Major_Head_Code")
    smhcode = idx.get("Sub_Major_Head_Code")
    mincode = idx.get("Minor_Head_Code")
    shc = idx.get("Sub_Head_Code")
    dhc = idx.get("Detailed_Head_Code")
    ohc = idx.get("Object_Head_Code")
    rl  = idx.get("Row_Level")
    rt  = idx.get("Row_Type")
    desc = idx.get("Description")

    # Financial column indices
    fin_cols = [
        idx.get("Accounts_2018_19"),
        idx.get("Budget_2019_20"),
        idx.get("Revised_2019_20"),
        idx.get("Budget_2020_21")
    ]

    def is_total(row):
        """Check if description contains 'Total'."""
        try:
            if desc is not None:
                desc_text = row[desc].strip().lower()
                return "total" in desc_text
        except Exception:
            pass
        return False

    def has_financial_data(row):
        """Check if any financial column has a value."""
        try:
            for col_idx in fin_cols:
                if col_idx is not None and row[col_idx].strip():
                    return True
        except Exception:
            pass
        return False

    new_rows = [header]
    for row in rows[1:]:
        # Ensure row has enough columns
        while len(row) < len(header):
            row.append("")

        # Pad Major_Head_Code to 4
        if mhcode is not None and row[mhcode].strip():
            row[mhcode] = _pad(row[mhcode], 4)

        # Pad Sub_Major_Head_Code to 2
        if smhcode is not None and row[smhcode].strip():
            row[smhcode] = _pad(row[smhcode], 2)

        # Pad Minor_Head_Code to 3
        if mincode is not None and row[mincode].strip():
            row[mincode] = _pad(row[mincode], 3)

        # Pad Sub_Head_Code to 1
        if shc is not None and row[shc].strip():
            row[shc] = _pad(row[shc], 1)

        # Pad Detailed_Head_Code to 2
        if dhc is not None and row[dhc].strip():
            row[dhc] = _pad(row[dhc], 2)

        # Pad Object_Head_Code to 3 (only for Object-Head rows)
        if rl is not None and ohc is not None:
            if row[rl].strip() == "Object-Head" and row[ohc].strip():
                row[ohc] = _pad(row[ohc], 3)

        # Set Row_Type using decision tree
        if rt is not None:
            if not row[rt].strip():
                if is_total(row):
                    row[rt] = "Total"
                elif not has_financial_data(row):
                    row[rt] = "Header"
                else:
                    row[rt] = "Data"

        new_rows.append(row)

    out = StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerows(new_rows)
    return out.getvalue().strip()

def normalize_minor_head_csv(csv_text: str) -> str:
    """
    Schema-aware pass for minor_head_summary_csv that:
      - Pads Major_Head_Code to 4, Sub_Major_Head_Code to 2, Minor_Head_Code to 3
      - Sets Row_Type based on rules
    """
    import csv
    from io import StringIO

    if not csv_text.strip():
        return csv_text

    reader = csv.reader(StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return csv_text

    header = rows[0]
    idx = {name: i for i, name in enumerate(header)}

    # Required columns indices
    mhcode = idx.get("Major_Head_Code")
    smhcode = idx.get("Sub_Major_Head_Code")
    mincode = idx.get("Minor_Head_Code")
    rt  = idx.get("Row_Type")
    desc = idx.get("Description")

    # Financial column indices
    fin_cols = [
        idx.get("Accounts_2018_19"),
        idx.get("Budget_2019_20"),
        idx.get("Revised_2019_20"),
        idx.get("Budget_2020_21")
    ]

    def is_total(row):
        try:
            if desc is not None:
                desc_text = row[desc].strip().lower()
                return "total" in desc_text
        except Exception:
            pass
        return False

    def has_financial_data(row):
        try:
            for col_idx in fin_cols:
                if col_idx is not None and row[col_idx].strip():
                    return True
        except Exception:
            pass
        return False

    new_rows = [header]
    for row in rows[1:]:
        # Ensure row has enough columns
        while len(row) < len(header):
            row.append("")

        # Pad codes
        if mhcode is not None and row[mhcode].strip():
            row[mhcode] = _pad(row[mhcode], 4)
        if smhcode is not None and row[smhcode].strip():
            row[smhcode] = _pad(row[smhcode], 2)
        if mincode is not None and row[mincode].strip():
            row[mincode] = _pad(row[mincode], 3)

        # Set Row_Type
        if rt is not None:
            if not row[rt].strip():
                if is_total(row):
                    row[rt] = "Total"
                elif not has_financial_data(row):
                    row[rt] = "Header"
                else:
                    row[rt] = "Data"

        new_rows.append(row)

    out = StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerows(new_rows)
    return out.getvalue().strip()

# ============================================================================
# STEP 2: Extract Data Using Gemini
# ============================================================================

def extract_data_with_gemini(config):
    """Call Gemini with the current page, and return a CSV

    Take the existing page image, pass it to Gemini with the context
    of the previous page, in case the table continues from previous
    pages.  The prompt requests the different metadata, and this saves
    those intermediate tables in files on disk.

    """
    print("\n" + "=" * 80)
    print("STEP 2: Extracting data using Gemini AI")
    print("=" * 80)

    if not API_KEY:
        print("ERROR: GEMINI_API_KEY not found in environment variables")
        sys.exit(1)

    try:
        client = genai.Client(api_key=API_KEY)
        print(f"✅ Initialized Gemini client (model: {config['GEMINI_MODEL']})")
    except Exception as e:
        print(f"ERROR initializing Gemini client: {e}")
        sys.exit(1)

    primary_prompt = read_prompt_text(config)

    config['JSON_DIR'].mkdir(parents=True, exist_ok=True)
    config['CSV_DIR'].mkdir(parents=True, exist_ok=True)
    config['CSV_DIR_SUB_MAJOR_HEAD'].mkdir(parents=True, exist_ok=True)
    config['CSV_DIR_MINOR_HEAD'].mkdir(parents=True, exist_ok=True)
    config['CSV_DIR_SUB_HEAD'].mkdir(parents=True, exist_ok=True)
    config['CSV_DIR_DETAILED'].mkdir(parents=True, exist_ok=True)
    config['CSV_DIR_OBJECT_HEAD'].mkdir(parents=True, exist_ok=True)

    # Filter images to only include pages within START_PAGE to END_PAGE range
    image_files = sorted([
        f for f in os.listdir(config['IMAGES_DIR'])
        if f.lower().endswith(".jpg") and
        config['START_PAGE'] <= int(re.search(r'page_(\d+)', f).group(1)) <= config['END_PAGE']
    ])
    if not image_files:
        print(f"ERROR: No JPG images found in {config['IMAGES_DIR']}")
        sys.exit(1)

    print(f"Found {len(image_files)} images to process\n")

    previous_sub_major_csv = ""
    previous_minor_head_csv = ""
    previous_sub_head_csv = ""
    previous_detailed_csv = ""
    previous_object_csv = ""
    skipped = 0

    # Cost, in terms of tokens
    total_prompt_tokens = 0
    total_candidate_tokens = 0
    total_thought_tokens = 0

    for i, filename in enumerate(image_files):
        file_path = config['IMAGES_DIR'] / filename
        stem = Path(filename).stem

        json_exists = (config['JSON_DIR'] / f"{stem}.json").exists()

        if json_exists:
            print(f"[{i+1}/{len(image_files)}] ⏭️  Skipping {filename} (already processed)")
            skipped += 1

            # Load previous CSVs for context continuity - load whatever exists from this page
            try:
                previous_sub_major_csv = (config['CSV_DIR_SUB_MAJOR_HEAD'] / f"{stem}_sub_major.csv").read_text(encoding="utf-8")
            except:
                pass

            try:
                previous_minor_head_csv = (config['CSV_DIR_MINOR_HEAD'] / f"{stem}_minor.csv").read_text(encoding="utf-8")
            except:
                pass

            try:
                previous_sub_head_csv = (config['CSV_DIR_SUB_HEAD'] / f"{stem}_sub_head.csv").read_text(encoding="utf-8")
            except:
                pass

            try:
                previous_detailed_csv = (config['CSV_DIR_DETAILED'] / f"{stem}_detailed.csv").read_text(encoding="utf-8")
            except:
                pass

            try:
                previous_object_csv = (config['CSV_DIR_OBJECT_HEAD'] / f"{stem}_object.csv").read_text(encoding="utf-8")
            except:
                pass

            continue

        print(f"[{i+1}/{len(image_files)}] Processing: {filename}")

        try:
            img = Image.open(file_path)

            content = [primary_prompt]
            if i > 0 and (previous_sub_major_csv or previous_minor_head_csv or previous_sub_head_csv or previous_detailed_csv or previous_object_csv):
                content.append(
                    "IMPORTANT CONTEXT: Use the following CSV data from the previous page "
                    f"({image_files[i-1]}) for state carry-forward only. "
                    "Do NOT duplicate any rows from it in your output for the current page."
                )

                if previous_sub_major_csv:
                    content.append("previous_sub_major_head_summary_csv:")
                    content.append(previous_sub_major_csv)

                if previous_minor_head_csv:
                    content.append("previous_minor_head_summary_csv:")
                    content.append(previous_minor_head_csv)

                if previous_sub_head_csv:
                    content.append("previous_sub_head_summary_csv:")
                    content.append(previous_sub_head_csv)

                if previous_detailed_csv:
                    content.append("previous_detailed_csv:")
                    content.append(previous_detailed_csv)

                if previous_object_csv:
                    content.append("previous_object_head_summary_csv:")
                    content.append(previous_object_csv)

            # Final Part: The image for the current page
            content.append(img)

            generate_config = types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            )

            response = client.models.generate_content(
                model=config['GEMINI_MODEL'],
                contents=content,
                config=generate_config
            )

            # Add cost to running total
            r = response.usage_metadata
            total_prompt_tokens =  total_prompt_tokens + r.prompt_token_count
            total_candidate_tokens = total_candidate_tokens + r.candidates_token_count
            total_thought_tokens = total_thought_tokens + r.thoughts_token_count

            json_text = response.text.strip()

            # Save the raw JSON response
            json_filename = config['JSON_DIR'] / f"{Path(filename).stem}.json"
            json_filename.write_text(json_text, encoding="utf-8")

            # Parse the JSON to get the CSVs
            data = json.loads(json_text)
            current_sub_major_csv = data.get("sub_major_head_summary_csv", "")
            current_minor_head_csv = data.get("minor_head_summary_csv", "")
            current_sub_head_csv = data.get("sub_head_summary_csv", "")
            current_detailed_csv = data.get("detailed_csv", "")
            current_object_csv = data.get("object_head_summary_csv", "")

            # Save the individual CSV files
            if current_sub_major_csv:
                csv_sub_major_path = config['CSV_DIR_SUB_MAJOR_HEAD'] / f"{Path(filename).stem}_sub_major.csv"
                csv_sub_major_path.write_text(current_sub_major_csv, encoding="utf-8")

            if current_minor_head_csv:
                csv_minor_path = config['CSV_DIR_MINOR_HEAD'] / f"{Path(filename).stem}_minor.csv"
                csv_minor_path.write_text(current_minor_head_csv, encoding="utf-8")

            if current_sub_head_csv:
                csv_sub_head_path = config['CSV_DIR_SUB_HEAD'] / f"{Path(filename).stem}_sub_head.csv"
                csv_sub_head_path.write_text(current_sub_head_csv, encoding="utf-8")

            if current_detailed_csv:
                csv_detailed_path = config['CSV_DIR_DETAILED'] / f"{Path(filename).stem}_detailed.csv"
                csv_detailed_path.write_text(current_detailed_csv, encoding="utf-8")

            if current_object_csv:
                csv_object_path = config['CSV_DIR_OBJECT_HEAD'] / f"{Path(filename).stem}_object.csv"
                csv_object_path.write_text(current_object_csv, encoding="utf-8")

            # Update the state variables for the next iteration
            # Only update if the new CSV is not empty to preserve state across empty pages
            if current_sub_major_csv:
                previous_sub_major_csv = current_sub_major_csv
            if current_minor_head_csv:
                previous_minor_head_csv = current_minor_head_csv
            if current_sub_head_csv:
                previous_sub_head_csv = current_sub_head_csv
            if current_detailed_csv:
                previous_detailed_csv = current_detailed_csv
            if current_object_csv:
                previous_object_csv = current_object_csv

            print(f"✅ Successfully processed and saved output for {filename}")

        except Exception as e:
            print(f"  ❌ ERROR processing {filename}: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Save costs here
    cost_file = config['OUTPUT_BASE'] / "gemini_cost.txt"
    total_cost = f"""
    total_prompt_tokens: {total_prompt_tokens}
    total_candidate_tokens: {total_candidate_tokens}
    total_thought_tokens: {total_thought_tokens}
    """
    cost_file.write_text(total_cost, encoding="utf-8")


    print(f"\n✅ Completed Gemini extraction: {len(image_files) - skipped} processed, {skipped} skipped")

# ============================================================================
# STEP 3: Clean and Validate CSVs (import from csv_cleaner.py)
# ============================================================================

def run_csv_cleaner(config):
    """Run CSV cleaning and validation for all 5 CSV types, return structured results."""
    print("" + "=" * 80)
    print("STEP 3: Cleaning and Validating CSVs")
    print("=" * 80)

    # Import the CSVFileProcessor and CleaningLogger classes
    import sys
    sys.path.insert(0, str(config['PROJECT_ROOT'] / "SRC/15_sr_ka_exp"))
    from csv_cleaner import CSVFileProcessor, CleaningLogger

    csv_dir = config['OUTPUT_BASE'] / "csv_outputs"
    cleaned_dir = config['OUTPUT_BASE'] / "csv_cleaned"
    log_dir = config['OUTPUT_BASE'] / "cleaning_logs"

    # Create logger instance
    logger = CleaningLogger(log_dir)

    logger.append_text("=" * 72)
    logger.append_text("CSV CLEANUP LOG")
    logger.append_text("=" * 72)
    logger.append_text(f"Input location : {csv_dir}")
    logger.append_text(f"Output location: {cleaned_dir}")
    logger.append_text("")

    overall_reports = []

    # Define all CSV types to process
    csv_types = [
        ("sub_major_head_summary_csv", "sub_major_head", SUB_MAJOR_HEAD_SCHEMA),
        ("minor_head_summary_csv", "minor_head", MINOR_HEAD_SCHEMA),
        ("sub_head_summary_csv", "sub_head", SUB_HEAD_SCHEMA),
        ("detailed_head_summary_csv", "detailed_head", DETAILED_HEAD_SCHEMA),
        ("object_head_summary_csv", "object_head", OBJECT_HEAD_SCHEMA),
    ]

    # Process each CSV type
    for folder, schema_name, schema in csv_types:
        input_dir = csv_dir / folder
        output_dir = cleaned_dir / folder

        print(f"\nProcessing {schema_name.replace('_', ' ').title()} ({folder})")
        logger.append_text(f"Processing {schema_name} ({folder})")

        if not input_dir.exists():
            print(f"  Skipping: directory not found ({input_dir})")
            logger.append_text(f"  Skipping: directory not found ({input_dir})")
            logger.append_text("")
            continue

        if not list(input_dir.glob("*.csv")):
            print(f"  Skipping: no CSV files found")
            logger.append_text(f"  Skipping: no CSV files found")
            logger.append_text("")
            continue

        processor = CSVFileProcessor(schema_name, schema)
        reports = processor.process_directory(
            input_dir, output_dir, schema_name, logger
        )
        overall_reports.extend(reports)
        print("")
        logger.append_text("")

    # Print overall summary
    if overall_reports:
        total_files = len(overall_reports)
        total_rows = sum(r.cleaned_rows for r in overall_reports)
        total_rows_without_errors = sum(r.rows_without_errors() for r in overall_reports)
        total_rows_with_issues = sum(r.rows_with_issues() for r in overall_reports)
        total_rows_errors_corrected = sum(r.rows_with_errors_corrected() for r in overall_reports)
        total_rows_errors_uncorrected = sum(r.rows_with_errors_uncorrected() for r in overall_reports)
        total_issues = sum(r.issue_count for r in overall_reports)

        aggregate_breakdown = {}
        for report in overall_reports:
            for code, count in report.issue_counts_by_code().items():
                aggregate_breakdown[code] = aggregate_breakdown.get(code, 0) + count

        print("=" * 72)
        print("OVERALL SUMMARY")
        print("=" * 72)
        print(f"Files processed      : {total_files}")
        print(f"Total rows           : {total_rows}")
        print(f"Rows without errors  : {total_rows_without_errors}")
        print(f"Rows with errors     : {total_rows_with_issues}")
        print(f"  - Errors corrected : {total_rows_errors_corrected}")
        print(f"  - Errors uncorrected: {total_rows_errors_uncorrected}")
        print(f"Total issues         : {total_issues}")
        if aggregate_breakdown:
            print("Issue breakdown      :")
            for code, count in sorted(
                aggregate_breakdown.items(), key=lambda item: item[1], reverse=True
            ):
                print(f"  - {code}: {count}")

        logger.append_text("=" * 72)
        logger.append_text("OVERALL SUMMARY")
        logger.append_text("=" * 72)
        logger.append_text(f"Files processed      : {total_files}")
        logger.append_text(f"Total rows           : {total_rows}")
        logger.append_text(f"Rows without errors  : {total_rows_without_errors}")
        logger.append_text(f"Rows with errors     : {total_rows_with_issues}")
        logger.append_text(f"  - Errors corrected : {total_rows_errors_corrected}")
        logger.append_text(f"  - Errors uncorrected: {total_rows_errors_uncorrected}")
        logger.append_text(f"Total issues         : {total_issues}")
        if aggregate_breakdown:
            logger.append_text("Issue breakdown      :")
            for code, count in sorted(
                aggregate_breakdown.items(), key=lambda item: item[1], reverse=True
            ):
                logger.append_text(f"  - {code}: {count}")
    else:
        print("No CSV files were processed.")
        logger.append_text("No CSV files were processed.")

    # Record overall summary for CSV export
    logger.record_overall_summary(overall_reports)

    # Save all logs
    logger.save()

    print(f"\n📊 Cleaning logs saved to: {log_dir}")
    print(f"  - cleaning_report_{{timestamp}}.txt (text summary)")
    print(f"  - cleaning_issues_{{timestamp}}.csv (row breakdown: File, Page, Row, Has_Error)")
    print(f"  - cleaning_issues_detailed_{{timestamp}}.csv (full error details)")
    print(f"  - cleaning_summary_{{timestamp}}.csv (aggregated statistics)")

    print("\n✅ CSV cleaning completed")
    return overall_reports


# ============================================================================
# STEP 4: Combine Validated CSVs (import from csv_combine_validated.py)
# ============================================================================

def run_csv_combiner(config):
    """Run CSV combination for all 5 CSV types using cleaned CSVs."""
    print("" + "=" * 80)
    print("STEP 4: Combining Validated CSVs")
    print("=" * 80)

    # Import the combination function
    import sys
    sys.path.insert(0, str(config['PROJECT_ROOT'] / "SRC/15_sr_ka_exp"))
    from csv_combine_validated import combine_csv_files

    cleaned_dir = config['OUTPUT_BASE'] / "csv_cleaned"

    # Define all CSV types to combine
    csv_types = [
        ("sub_major_head_summary_csv", "Sub-Major Head Summary", SUB_MAJOR_HEAD_SCHEMA, "final_sub_major_head_summary.csv"),
        ("minor_head_summary_csv", "Minor Head Summary", MINOR_HEAD_SCHEMA, "final_minor_head_summary.csv"),
        ("sub_head_summary_csv", "Sub-Head Summary", SUB_HEAD_SCHEMA, "final_sub_head_summary.csv"),
        ("detailed_head_summary_csv", "Detailed Head Summary", DETAILED_HEAD_SCHEMA, "final_detailed_head_summary.csv"),
        ("object_head_summary_csv", "Object Head Summary", OBJECT_HEAD_SCHEMA, "final_object_head_summary.csv"),
    ]

    success_count = 0
    output_files = []

    # Combine each CSV type
    for csv_type_dir, display_name, schema, output_filename in csv_types:
        cleaned_type_dir = cleaned_dir / csv_type_dir
        final_output = config['OUTPUT_BASE'] / output_filename

        print("\n" + "=" * 40)
        if cleaned_type_dir.exists() and list(cleaned_type_dir.glob("*.csv")):
            if combine_csv_files(cleaned_type_dir, final_output, schema, display_name):
                success_count += 1
                output_files.append((display_name, final_output))
        else:
            print(f"⚠️  No cleaned {display_name} CSVs to combine")

    # Final summary
    total_types = len(csv_types)
    if success_count == total_types:
        print(f"\n✅ CSV combination completed: All {total_types} CSV types combined successfully")
        return True
    elif success_count > 0:
        print(f"\n⚠️  Partial success: {success_count}/{total_types} CSV types combined")
        return True
    else:
        print("\n❌ CSV combination failed: No CSV files combined")
        return False

# ============================================================================
# STEP 5: Run Validation (import from run_validation.py)
# ============================================================================

def run_validation(config):
    """Run hierarchical validation on combined CSVs."""
    print("" + "=" * 80)
    print("STEP 5: Running Hierarchical Validation")
    print("=" * 80)

    # Import the validation function
    import sys
    sys.path.insert(0, str(config['PROJECT_ROOT'] / "SRC/15_sr_ka_exp"))
    from run_validation import main as run_validation_main

    try:
        _, summary = run_validation_main(output_prefix='validation')

        if summary is not None and not summary.empty:
            print("\n✅ Validation completed successfully")

            # Show quick summary
            total_checks = summary['Total_Checks'].sum()
            total_passed = summary['Passed'].sum()
            total_failed = summary['Failed'].sum()
            overall_pass_rate = (total_passed / total_checks * 100) if total_checks > 0 else 0

            print(f"\n📊 Validation Summary:")
            print(f"   Total checks: {total_checks}")
            print(f"   Passed: {total_passed}")
            print(f"   Failed: {total_failed}")
            print(f"   Overall pass rate: {overall_pass_rate:.2f}%")

            return True
        else:
            print("\n⚠️  Validation completed but no results generated")
            return False

    except Exception as e:
        print(f"\n❌ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# MAIN
# ============================================================================

def main():
    # Argument handling
    parser = argparse.ArgumentParser(
        prog="extract_workflow",
        description='Extract text from pdf files by calling GenAI models')
    parser.add_argument('-m', '--model',
                        default='gemini-2.5-pro',
                        help='Name of the model to call, by default gemini-2.5-pro')
    parser.add_argument('-c', '--config',
                        default='CONFIG/config.txt',
                        help='Config filename for input data and prompts, by default config.txt')

    parser.add_argument('-f', '--file-path',
                        default="DATA/All_States/KA_2020-21/07-EXPVOL-05.pdf",
                        help='PDF File to extract from')
    parser.add_argument('-p', '--prompt-path',
                        default="PROMPTS/15_sr_ka_exp/15_sr_ka_exp_v2.md",
                        help='Prompt file-path for extraction')
    parser.add_argument('-s', '--start-page',
                        default='12',
                        help='Start page for extraction')
    parser.add_argument('-e', '--end-page',
                        default='57',
                        help='End page for extraction')
    parser.add_argument('-o', '--out-path',
                        default="OUT/15_sr_ka_exp",
                        help='Base output TO where we extract files')
    args = parser.parse_args()

    config = {}

    # TODO(viki): Be smart about it, if we're in the SRC directory, then
    # just take one parent.
    config['PROJECT_ROOT'] = Path(__file__).parent.parent.parent

    # Get configuration options here.
    config['PDF_PATH'] = config['PROJECT_ROOT'] / args.file_path
    config['OUTPUT_BASE'] = config['PROJECT_ROOT'] / args.out_path
    config['PROMPT_FILE'] = config['PROJECT_ROOT'] / args.prompt_path

    config['START_PAGE'] = int(args.start_page)
    config['END_PAGE'] = int(args.end_page)

    config['GEMINI_MODEL'] = args.model

    # Validate the commandline inputs here, please


    # Output directories
    config['IMAGES_DIR'] = config['OUTPUT_BASE'] / "images"
    config['JSON_DIR'] = config['OUTPUT_BASE'] / "json_outputs"
    config['CSV_DIR'] = config['OUTPUT_BASE'] / "csv_outputs"
    config['CSV_DIR_SUB_MAJOR_HEAD'] = config['CSV_DIR'] / "sub_major_head_summary_csv"
    config['CSV_DIR_MINOR_HEAD'] = config['CSV_DIR'] / "minor_head_summary_csv"
    config['CSV_DIR_SUB_HEAD'] = config['CSV_DIR'] / "sub_head_summary_csv"
    config['CSV_DIR_DETAILED'] = config['CSV_DIR'] / "detailed_head_summary_csv"
    config['CSV_DIR_OBJECT_HEAD'] = config['CSV_DIR'] / "object_head_summary_csv"

    print("" + "=" * 80)
    print("KARNATAKA BUDGET EXTRACTION WORKFLOW")
    print("=" * 80)
    print(f"Project root: {config['PROJECT_ROOT']}")
    print(f"PDF source: {config['PDF_PATH']}")
    print(f"Pages to extract: {config['START_PAGE']}-{config['END_PAGE']}")
    print(f"Output directory: {config['OUTPUT_BASE']}")

    try:
        # Step 1: Extract PDF to images
        extract_pdf_to_images(config)

        # Step 2: Process with Gemini
        extract_data_with_gemini(config)

        # Step 3: Clean and validate CSVs
        run_csv_cleaner(config)

        # Step 4: Combine validated CSVs
        run_csv_combiner(config)

        # Step 5: Run hierarchical validation
        run_validation(config)

        print("" + "=" * 80)
        print("🎉 WORKFLOW COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print(f"Final outputs:")

        # List all possible final output files
        final_files = [
            ("Sub-Major Head Summary", config['OUTPUT_BASE'] / "final_sub_major_head_summary.csv"),
            ("Minor Head Summary", config['OUTPUT_BASE'] / "final_minor_head_summary.csv"),
            ("Sub-Head Summary", config['OUTPUT_BASE'] / "final_sub_head_summary.csv"),
            ("Detailed Head Summary", config['OUTPUT_BASE'] / "final_detailed_head_summary.csv"),
            ("Object Head Summary", config['OUTPUT_BASE'] / "final_object_head_summary.csv"),
        ]

        for name, path in final_files:
            if path.exists():
                print(f"  ✓ {name}: {path}")

        logs_dir = config['OUTPUT_BASE'] / "cleaning_logs"
        if logs_dir.exists():
            print(f"\n📊 Cleaning logs: {logs_dir}")

        validation_summary = config['OUTPUT_BASE'] / "validation_summary.csv"
        if validation_summary.exists():
            print(f"✅ Validation summary: {validation_summary}")

    except KeyboardInterrupt:
        print("⚠️  Workflow interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
