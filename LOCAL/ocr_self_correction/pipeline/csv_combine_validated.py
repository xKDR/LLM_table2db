#!/usr/bin/env python3
"""Improved CSV Combination Script with Validation.

This script combines cleaned CSV files into summary files. It performs strict
validation of the CSV structure (column counts and headers) and skips rows
that were flagged with errors during the cleaning process.
"""

import csv
import re
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

# Import shared schemas
from schemas import (
    SUB_MAJOR_HEAD_SCHEMA,
    MINOR_HEAD_SCHEMA,
    SUB_HEAD_SCHEMA,
    DETAILED_HEAD_SCHEMA,
    OBJECT_HEAD_SCHEMA,
)


def extract_page_number(filename: str) -> int:
    """Extracts page number from a filename for sorting purposes.

    Args:
        filename: The name of the file to extract the page number from.

    Returns:
        The extracted page number as an integer. Returns 999999 if no number
        is found to ensure it sorts to the end.
    """
    match = re.search(r"page[_-]?0*(\d+)", filename, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Fallback: extract last number
    nums = re.findall(r"(\d+)", filename)
    if nums:
        return int(nums[-1])

    return 999999  # Put at end if no number found


def validate_csv_structure(
    file_path: Path, expected_schema: List[str]
) -> Tuple[bool, str]:
    """Validates that a CSV file matches the expected column structure and names.

    Args:
        file_path: Path to the CSV file to validate.
        expected_schema: A list of expected column header names.

    Returns:
        A tuple of (is_valid, message), where is_valid is a boolean and message
        describes the result or any specific mismatches found.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="|")
            header = next(reader, None)

            if not header:
                return False, "Empty file"

            if len(header) != len(expected_schema):
                return (
                    False,
                    f"Column count mismatch: expected {len(expected_schema)}, got {len(header)}",
                )

            # Check if header matches expected schema
            mismatches = []
            for i, (expected, actual) in enumerate(zip(expected_schema, header)):
                if expected != actual:
                    mismatches.append(f"Col {i}: expected '{expected}', got '{actual}'")

            if mismatches:
                return False, "; ".join(mismatches[:3])  # Show first 3 mismatches

            return True, "OK"

    except Exception as e:
        return False, f"Error reading file: {str(e)}"


def load_error_rows(cleaning_issues_path: Path) -> Set[Tuple[str, int]]:
    """Loads a set of (filename, row_number) pairs that should be skipped.

    Args:
        cleaning_issues_path: Path to the CSV file containing cleaning issues.

    Returns:
        A set of tuples, each containing a filename (str) and a row number (int).
    """
    error_rows = set()

    if not cleaning_issues_path.exists():
        print(f"⚠️  Warning: cleaning_issues file not found at {cleaning_issues_path}")
        return error_rows

    try:
        with open(cleaning_issues_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Has_Error", "").lower() == "yes":
                    filename = row.get("File_Name", "")
                    row_num = row.get("Row_Number", "")
                    if filename and row_num:
                        error_rows.add((filename, int(row_num)))

        print(f"  Loaded {len(error_rows)} rows with errors from cleaning report")
    except Exception as e:
        print(f"⚠️  Warning: Could not read cleaning_issues file: {e}")

    return error_rows


def combine_csv_files(
    input_dir: Path,
    output_file: Path,
    expected_schema: List[str],
    archetype_name: str,
    error_rows: Optional[Set[Tuple[str, int]]] = None,
) -> bool:
    """Combines multiple CSV files into a single output file with validation.

    Args:
        input_dir: Directory containing CSV files to combine.
        output_file: Path to the combined output file.
        expected_schema: A list of expected column header names.
        archetype_name: A descriptive name for the CSV type being combined
            (e.g., "Minor Head Summary").
        error_rows: A set of (filename, row_number) pairs representing rows
            that should be skipped during combination.

    Returns:
        True if the combination process was successful, False otherwise.
    """
    if error_rows is None:
        error_rows = set()

    print(f"\n{'='*80}")
    print(f"COMBINING: {archetype_name}")
    print(f"{'='*80}")
    print(f"Input directory: {input_dir}")
    print(f"Output file: {output_file}")

    if not input_dir.exists():
        print(f"❌ Error: Input directory does not exist")
        return False

    # Get all CSV files, sorted by page number
    csv_files = sorted(
        input_dir.glob("*.csv"),
        key=lambda f: (extract_page_number(f.name), f.name.lower()),
    )

    if not csv_files:
        print(f"⚠️  Warning: No CSV files found")
        return False

    print(f"Found {len(csv_files)} CSV files")

    # Validate all files first
    print("\nValidating files...")
    invalid_files = []

    for csv_file in csv_files:
        is_valid, message = validate_csv_structure(csv_file, expected_schema)
        if not is_valid:
            invalid_files.append((csv_file.name, message))
            print(f"  ❌ {csv_file.name}: {message}")
        else:
            print(f"  ✓ {csv_file.name}")

    if invalid_files:
        print(f"\n❌ Error: {len(invalid_files)} file(s) have invalid structure")
        print("Please fix these files before combining")
        return False

    # All files valid, proceed with combination
    print(f"\n✓ All files validated successfully")
    print("Combining files...")

    combined_rows = []
    total_data_rows = 0

    for i, csv_file in enumerate(csv_files, 1):
        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.reader(f, delimiter="|")

                # Skip header for all files
                header = next(reader)

                # Add all data rows (never drop rows — validation needs full coverage)
                file_rows = 0

                for row in reader:
                    # Skip empty rows
                    if not any(cell.strip() for cell in row):
                        continue

                    combined_rows.append(row)
                    file_rows += 1

                total_data_rows += file_rows
                print(f"  [{i}/{len(csv_files)}] {csv_file.name}: {file_rows} rows")

        except Exception as e:
            print(f"  ❌ Error reading {csv_file.name}: {e}")
            return False

    if not combined_rows:
        print(f"\n⚠️  Warning: No data rows found in any file")
        return False

    # Write combined output
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="|")

            # Write header
            writer.writerow(expected_schema)

            # Write all data rows
            writer.writerows(combined_rows)

        print(f"\n✅ Successfully combined {len(csv_files)} files")
        print(f"   Total data rows: {total_data_rows}")
        print(f"   Output: {output_file}")

        return True

    except Exception as e:
        print(f"\n❌ Error writing output file: {e}")
        return False


def main():
    """Main entry point for combining all 5 budget CSV types.

    This function sets up paths, loads error row information, and orchestrates
     the combination process for each of the five budget hierarchy levels.
    """
    # Argument handling
    import argparse

    parser = argparse.ArgumentParser(
        prog="csv_combiner",
        description="Combine cleaned CSV files into final summaries",
    )
    parser.add_argument(
        "-o",
        "--out-path",
        default="OUT/23_sr_ka_exp",
        help="Base output directory containing csv_cleaned/",
    )
    args = parser.parse_args()

    # Determine paths
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent

    # Use provided path
    output_base = Path(args.out_path)
    if not output_base.is_absolute():
        output_base = project_root / output_base
    
    if not output_base.exists():
        print(f"Error: Output base directory does not exist: {output_base}")
        sys.exit(1)

    # Use cleaned CSVs as input
    cleaned_dir = output_base / "csv_cleaned"
    cleaning_logs_dir = output_base / "cleaning_logs"

    print("\n" + "=" * 80)
    print("CSV COMBINATION SCRIPT (WITH VALIDATION)")
    print("=" * 80)
    print(f"Script location: {script_dir}")
    print(f"Project root: {project_root}")
    print(f"Using cleaned CSVs from: {cleaned_dir}")

    # Find the most recent cleaning_issues CSV file
    cleaning_issues_files = sorted(
        cleaning_logs_dir.glob("cleaning_issues_*.csv"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    error_rows = set()
    if cleaning_issues_files:
        latest_issues_file = cleaning_issues_files[0]
        print(f"Loading error rows from: {latest_issues_file.name}")
        error_rows = load_error_rows(latest_issues_file)
    else:
        print(
            "⚠️  No cleaning_issues file found - combining all rows without filtering"
        )
        print(f"   (Looking in: {cleaning_logs_dir})")

    # Define all CSV types to combine
    csv_types = [
        (
            "sub_major_head_summary_csv",
            "Sub-Major Head Summary",
            SUB_MAJOR_HEAD_SCHEMA,
            "final_sub_major_head_summary.csv",
        ),
        (
            "minor_head_summary_csv",
            "Minor Head Summary",
            MINOR_HEAD_SCHEMA,
            "final_minor_head_summary.csv",
        ),
        (
            "sub_head_summary_csv",
            "Sub-Head Summary",
            SUB_HEAD_SCHEMA,
            "final_sub_head_summary.csv",
        ),
        (
            "detailed_head_summary_csv",
            "Detailed Head Summary",
            DETAILED_HEAD_SCHEMA,
            "final_detailed_head_summary.csv",
        ),
        (
            "object_head_summary_csv",
            "Object Head Summary (Most Granular)",
            OBJECT_HEAD_SCHEMA,
            "final_object_head_summary.csv",
        ),
    ]

    success_count = 0
    output_files = []

    # Combine each CSV type
    for csv_type_dir, display_name, schema, output_filename in csv_types:
        cleaned_type_dir = cleaned_dir / csv_type_dir
        final_output = output_base / output_filename

        if combine_csv_files(
            cleaned_type_dir, final_output, schema, display_name, error_rows
        ):
            success_count += 1
            output_files.append((display_name, final_output))

    # Final summary
    print("\n" + "=" * 80)
    if success_count == len(csv_types):
        print(f"✅ SUCCESS: All {len(csv_types)} CSV types combined successfully!")
    elif success_count > 0:
        print(
            f"⚠️  PARTIAL SUCCESS: {success_count}/{len(csv_types)} CSV types combined successfully"
        )
    else:
        print("❌ FAILURE: No CSV files combined")
    print("=" * 80)

    if output_files:
        print("\nFinal outputs:")
        for name, path in output_files:
            if path.exists():
                print(f"  • {name}: {path}")


if __name__ == "__main__":
    main()