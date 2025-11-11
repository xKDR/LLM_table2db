#!/usr/bin/env python3
"""Utility to align, clean, and validate Karnataka budget CSV extracts.

The previous version of this script had grown large and hard to follow. This
rewrite keeps the critical behaviour while breaking the work into small,
testable units:

* make column counts match the expected schema, applying small shifts when needed
* normalise code and financial fields
* infer obvious Row_Type / Row_Level gaps
* enforce the core validation rules that downstream steps depend on
* emit concise per-file summaries so manual review stays easy
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from schemas import (
    SUB_MAJOR_HEAD_SCHEMA,
    MINOR_HEAD_SCHEMA,
    SUB_HEAD_SCHEMA,
    DETAILED_HEAD_SCHEMA,
    OBJECT_HEAD_SCHEMA,
)

# --------------------------------------------------------------------------- #
# Canonical values and shared configuration
# --------------------------------------------------------------------------- #

ROW_TYPE_VALUES: Tuple[str, ...] = ("Data", "Header", "Total")
ROW_LEVEL_VALUES: Tuple[str, ...] = (
    "Major-Head",
    "Sub-Major-Head",
    "Minor-Head",
    "Sub-Head",
    "Detailed-Head",
    "Object-Head",
)
VOTE_CHARGE_VALUES: Tuple[str, ...] = ("", "V", "C")
FINANCIAL_COLUMNS: Tuple[str, ...] = (
    "Accounts_2018_19",
    "Budget_2019_20",
    "Revised_2019_20",
    "Budget_2020_21",
)

ROW_TYPE_CANONICAL = {value.lower(): value for value in ROW_TYPE_VALUES}
ROW_LEVEL_CANONICAL = {value.lower(): value for value in ROW_LEVEL_VALUES}
VOTE_CHARGE_CANONICAL = {value.lower(): value for value in VOTE_CHARGE_VALUES}

NUMERIC_PATTERN = re.compile(r"^-?\d+(?:\.\d+)?$")
PAGE_PATTERN = re.compile(r"page[_-]?0*(\d+)", re.IGNORECASE)

# Expected widths for code columns per schema
CODE_RULES: Dict[str, Dict[str, int]] = {
    "sub_major_head": {
        "Major_Head_Code": 4,
        "Sub_Major_Head_Code": 2,
    },
    "minor_head": {
        "Major_Head_Code": 4,
        "Sub_Major_Head_Code": 2,
        "Minor_Head_Code": 3,
    },
    "sub_head": {
        "Major_Head_Code": 4,
        "Sub_Major_Head_Code": 2,
        "Minor_Head_Code": 3,
        "Sub_Head_Code": 1,
    },
    "detailed_head": {
        "Major_Head_Code": 4,
        "Sub_Major_Head_Code": 2,
        "Minor_Head_Code": 3,
        "Sub_Head_Code": 1,
        "Detailed_Head_Code": 2,
    },
    "object_head": {
        "Major_Head_Code": 4,
        "Sub_Major_Head_Code": 2,
        "Minor_Head_Code": 3,
        "Sub_Head_Code": 1,
        "Detailed_Head_Code": 2,
        "Object_Head_Code": 3,
    },
}

# Ordered hierarchy for inferring Row_Level and inheriting codes
HIERARCHY_LEVELS: Dict[str, List[Tuple[str, str]]] = {
    "sub_major_head": [
        ("Sub_Major_Head_Code", "Sub-Major-Head"),
        ("Major_Head_Code", "Major-Head"),
    ],
    "minor_head": [
        ("Minor_Head_Code", "Minor-Head"),
        ("Sub_Major_Head_Code", "Sub-Major-Head"),
        ("Major_Head_Code", "Major-Head"),
    ],
    "sub_head": [
        ("Sub_Head_Code", "Sub-Head"),
        ("Minor_Head_Code", "Minor-Head"),
        ("Sub_Major_Head_Code", "Sub-Major-Head"),
        ("Major_Head_Code", "Major-Head"),
    ],
    "detailed_head": [
        ("Detailed_Head_Code", "Detailed-Head"),
        ("Sub_Head_Code", "Sub-Head"),
        ("Minor_Head_Code", "Minor-Head"),
        ("Sub_Major_Head_Code", "Sub-Major-Head"),
        ("Major_Head_Code", "Major-Head"),
    ],
    "object_head": [
        ("Object_Head_Code", "Object-Head"),
        ("Detailed_Head_Code", "Detailed-Head"),
        ("Sub_Head_Code", "Sub-Head"),
        ("Minor_Head_Code", "Minor-Head"),
        ("Sub_Major_Head_Code", "Sub-Major-Head"),
        ("Major_Head_Code", "Major-Head"),
    ],
}


# --------------------------------------------------------------------------- #
# Result containers
# --------------------------------------------------------------------------- #

@dataclass
class Issue:
    row_number: int
    column: str
    message: str
    code: str
    fixed: bool = False
    severity: str = "error"


@dataclass
class RowResult:
    row_number: int
    row: List[str]
    changed: bool
    issues: List[Issue] = field(default_factory=list)


@dataclass
class FileReport:
    input_file: Path
    output_file: Path
    total_rows: int = 0
    cleaned_rows: int = 0
    rows_with_changes: int = 0
    issues: List[Issue] = field(default_factory=list)
    header_replaced: bool = False

    def add_row(self, row_result: RowResult) -> None:
        self.total_rows += 1
        self.cleaned_rows += 1
        if row_result.changed:
            self.rows_with_changes += 1
        self.issues.extend(row_result.issues)

    def issues_by_row(self) -> Dict[int, List[Issue]]:
        grouped: Dict[int, List[Issue]] = {}
        for issue in self.issues:
            grouped.setdefault(issue.row_number, []).append(issue)
        return grouped

    def issue_counts_by_code(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for issue in self.issues:
            counts[issue.code] = counts.get(issue.code, 0) + 1
        return counts

    def rows_with_issues(self) -> int:
        return len({issue.row_number for issue in self.issues if issue.row_number > 0})

    def rows_without_errors(self) -> int:
        """Count rows that have no issues at all."""
        return self.cleaned_rows - self.rows_with_issues()

    def rows_with_errors_corrected(self) -> int:
        """Count rows where all errors were fixed."""
        issues_by_row = self.issues_by_row()
        corrected_rows = 0
        for row_issues in issues_by_row.values():
            if row_issues and all(issue.fixed for issue in row_issues):
                corrected_rows += 1
        return corrected_rows

    def rows_with_errors_uncorrected(self) -> int:
        """Count rows with at least one unfixed error."""
        issues_by_row = self.issues_by_row()
        uncorrected_rows = 0
        for row_issues in issues_by_row.values():
            if any(not issue.fixed for issue in row_issues):
                uncorrected_rows += 1
        return uncorrected_rows

    def warnings_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def issue_count(self) -> int:
        return len(self.issues)


class CleaningLogger:
    """Collects per-run logs and writes them to disk."""

    def __init__(self, base_dir: Path):
        from datetime import datetime
        self.base_dir = base_dir
        self.timestamp = datetime.now()
        self.text_lines: List[str] = []
        self.entries: List[Dict[str, str]] = []
        self.row_breakdown: List[Dict[str, str]] = []
        self.summary_entries: List[Dict[str, any]] = []

    def append_text(self, line: str = "") -> None:
        self.text_lines.append(line)

    def record_summary(self, csv_type: str, folder_name: str, reports: List) -> None:
        """Record summary statistics for a CSV type."""
        if not reports:
            return

        total_rows = sum(r.cleaned_rows for r in reports)
        total_rows_without_errors = sum(r.rows_without_errors() for r in reports)
        total_rows_with_issues = sum(r.rows_with_issues() for r in reports)
        total_rows_errors_corrected = sum(r.rows_with_errors_corrected() for r in reports)
        total_rows_errors_uncorrected = sum(r.rows_with_errors_uncorrected() for r in reports)
        total_issues = sum(r.issue_count for r in reports)

        # Collect error breakdown for uncorrected errors only
        uncorrected_breakdown: Dict[str, int] = {}
        for report in reports:
            for issue in report.issues:
                if not issue.fixed:
                    uncorrected_breakdown[issue.code] = uncorrected_breakdown.get(issue.code, 0) + 1

        # Format breakdown as string
        breakdown_str = "; ".join(
            f"{code}: {count}"
            for code, count in sorted(uncorrected_breakdown.items(), key=lambda x: x[1], reverse=True)
        ) if uncorrected_breakdown else ""

        self.summary_entries.append({
            "CSV_Type": csv_type,
            "Folder": folder_name,
            "Files_Processed": len(reports),
            "Total_Rows": total_rows,
            "Rows_Without_Errors": total_rows_without_errors,
            "Rows_With_Errors": total_rows_with_issues,
            "Errors_Corrected": total_rows_errors_corrected,
            "Errors_Uncorrected": total_rows_errors_uncorrected,
            "Total_Issues": total_issues,
            "Uncorrected_Error_Breakdown": breakdown_str,
        })

    def record_overall_summary(self, all_reports: List) -> None:
        """Record overall summary statistics across all CSV types."""
        if not all_reports:
            return

        total_files = len(all_reports)
        total_rows = sum(r.cleaned_rows for r in all_reports)
        total_rows_without_errors = sum(r.rows_without_errors() for r in all_reports)
        total_rows_with_issues = sum(r.rows_with_issues() for r in all_reports)
        total_rows_errors_corrected = sum(r.rows_with_errors_corrected() for r in all_reports)
        total_rows_errors_uncorrected = sum(r.rows_with_errors_uncorrected() for r in all_reports)
        total_issues = sum(r.issue_count for r in all_reports)

        # Collect error breakdown for uncorrected errors only
        uncorrected_breakdown: Dict[str, int] = {}
        for report in all_reports:
            for issue in report.issues:
                if not issue.fixed:
                    uncorrected_breakdown[issue.code] = uncorrected_breakdown.get(issue.code, 0) + 1

        # Format breakdown as string
        breakdown_str = "; ".join(
            f"{code}: {count}"
            for code, count in sorted(uncorrected_breakdown.items(), key=lambda x: x[1], reverse=True)
        ) if uncorrected_breakdown else ""

        self.summary_entries.append({
            "CSV_Type": "OVERALL",
            "Folder": "ALL",
            "Files_Processed": total_files,
            "Total_Rows": total_rows,
            "Rows_Without_Errors": total_rows_without_errors,
            "Rows_With_Errors": total_rows_with_issues,
            "Errors_Corrected": total_rows_errors_corrected,
            "Errors_Uncorrected": total_rows_errors_uncorrected,
            "Total_Issues": total_issues,
            "Uncorrected_Error_Breakdown": breakdown_str,
        })

    def record_file(self, csv_type: str, report: FileReport) -> None:
        page_match = PAGE_PATTERN.search(report.input_file.name)
        page_number = page_match.group(1) if page_match else ""

        # Collect detailed issues (for reference)
        for issue in report.issues:
            self.entries.append(
                {
                    "CSV_Type": csv_type,
                    "File_Name": report.input_file.name,
                    "Page_Number": page_number,
                    "Row_Number": issue.row_number,
                    "Error_Type": issue.code,
                    "Fixed": "Yes" if issue.fixed else "No",
                    "Column": issue.column,
                    "Error_Message": issue.message,
                }
            )

        # Create row-level breakdown - only rows with UNFIXED errors
        issues_by_row = report.issues_by_row()

        # Track all rows processed (assuming they start from row 2, row 1 is header)
        for row_num in range(2, report.total_rows + 2):
            row_issues = issues_by_row.get(row_num, [])
            # Only mark as error if there are UNFIXED issues
            has_unfixed_error = any(not issue.fixed for issue in row_issues)

            self.row_breakdown.append(
                {
                    "File_Name": report.input_file.name,
                    "Page_Number": page_number,
                    "Row_Number": str(row_num),
                    "Has_Error": "Yes" if has_unfixed_error else "No",
                }
            )

    def save(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Generate timestamp string for filenames
        timestamp_str = self.timestamp.strftime('%Y%m%d_%H%M%S')

        text_path = self.base_dir / f"cleaning_report_{timestamp_str}.txt"
        detailed_csv_path = self.base_dir / f"cleaning_issues_detailed_{timestamp_str}.csv"
        breakdown_csv_path = self.base_dir / f"cleaning_issues_{timestamp_str}.csv"
        summary_csv_path = self.base_dir / f"cleaning_summary_{timestamp_str}.csv"

        with open(text_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(self.text_lines).rstrip() + "\n")

        # Write detailed issues CSV
        detailed_fieldnames = [
            "CSV_Type",
            "File_Name",
            "Page_Number",
            "Row_Number",
            "Error_Type",
            "Fixed",
            "Column",
            "Error_Message",
        ]

        with open(detailed_csv_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=detailed_fieldnames)
            writer.writeheader()
            for entry in self.entries:
                writer.writerow(entry)

        # Write simplified row breakdown CSV
        breakdown_fieldnames = [
            "File_Name",
            "Page_Number",
            "Row_Number",
            "Has_Error",
        ]

        with open(breakdown_csv_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=breakdown_fieldnames)
            writer.writeheader()
            for entry in self.row_breakdown:
                writer.writerow(entry)

        # Write summary statistics CSV
        summary_fieldnames = [
            "CSV_Type",
            "Folder",
            "Files_Processed",
            "Total_Rows",
            "Rows_Without_Errors",
            "Rows_With_Errors",
            "Errors_Corrected",
            "Errors_Uncorrected",
            "Total_Issues",
            "Uncorrected_Error_Breakdown",
        ]

        with open(summary_csv_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=summary_fieldnames)
            writer.writeheader()
            for entry in self.summary_entries:
                writer.writerow(entry)


# --------------------------------------------------------------------------- #
# Cleaning helpers
# --------------------------------------------------------------------------- #

def pad_code(value: str, width: int) -> str:
    """Return the code padded with leading zeros without dropping non-digits."""
    if not value:
        return ""

    stripped = value.strip()
    if stripped == "...":
        return ""

    digits = re.sub(r"[^\d]", "", stripped)
    if not digits:
        return stripped

    if len(digits) >= width:
        return digits

    return digits.zfill(width)


def clean_financial_value(value: str) -> str:
    """Normalise numeric strings while tolerating the usual artefacts."""
    if not value:
        return ""

    stripped = value.strip()
    if not stripped or stripped == "...":
        return ""

    normalised = "".join(ch for ch in stripped if not ch.isspace()).replace(",", "")
    dash_chars = {"-", "–", "—", "−", "‐", "‒"}
    if not normalised or set(normalised) <= dash_chars:
        return ""

    if NUMERIC_PATTERN.match(normalised):
        return normalised

    filtered = re.sub(r"[^0-9.\-]", "", normalised)
    if not any(ch.isdigit() for ch in filtered):
        return ""
    if filtered.count("-") > 1:
        filtered = filtered.replace("-", "")
        if normalised.startswith("-"):
            filtered = "-" + filtered

    if filtered.count(".") > 1:
        first = filtered.find(".")
        filtered = filtered[: first + 1] + filtered[first + 1 :].replace(".", "")

    return filtered


class HierarchyContext:
    """Tracks the last seen codes to support inheritance and inference."""

    def __init__(
        self,
        column_index: Dict[str, int],
        code_fields: Iterable[str],
        level_order: Sequence[Tuple[str, str]],
    ):
        self.column_index = column_index
        self.code_fields = list(code_fields)
        self.level_order = list(level_order)
        self.codes: Dict[str, str] = {field: "" for field in self.code_fields}

    def inherit_codes(self, row: List[str]) -> bool:
        changed = False
        for field in self.code_fields:
            idx = self.column_index.get(field)
            if idx is None or idx >= len(row):
                continue
            if not row[idx] and self.codes.get(field):
                row[idx] = self.codes[field]
                changed = True
        return changed

    def update(self, row: Sequence[str]) -> None:
        for field in self.code_fields:
            idx = self.column_index.get(field)
            if idx is None or idx >= len(row):
                continue
            value = row[idx].strip()
            if value:
                self.codes[field] = value

    def infer_level(self) -> str:
        for field, level in self.level_order:
            if self.codes.get(field):
                return level
        return ""


# --------------------------------------------------------------------------- #
# Row processing
# --------------------------------------------------------------------------- #

class RowProcessor:
    """Clean and validate individual rows."""

    def __init__(self, schema_name: str, schema: Sequence[str]):
        self.schema_name = schema_name
        self.schema = list(schema)
        self.expected_cols = len(schema)
        self.column_index = {name: idx for idx, name in enumerate(self.schema)}
        self.code_rules = CODE_RULES.get(schema_name, {})
        self.level_order = HIERARCHY_LEVELS.get(schema_name, [])
        self.financial_indices = [
            self.column_index[col]
            for col in FINANCIAL_COLUMNS
            if col in self.column_index
        ]

        self.row_type_idx = self.column_index.get("Row_Type")
        self.row_level_idx = self.column_index.get("Row_Level")
        self.vote_marker_idx = self.column_index.get("Vote_Charge_Marker")
        self.description_idx = self.column_index.get("Description")

    def create_context(self) -> HierarchyContext:
        return HierarchyContext(
            column_index=self.column_index,
            code_fields=self.code_rules.keys(),
            level_order=self.level_order,
        )

    def process(
        self,
        raw_row: Sequence[str],
        row_number: int,
        context: Optional[HierarchyContext],
    ) -> RowResult:
        working = list(raw_row)
        changed = False
        issues: List[Issue] = []

        working, aligned, align_issues = self._align_columns(working, row_number)
        changed |= aligned
        issues.extend(align_issues)

        working, normalised = self._normalise_cells(working)
        changed |= normalised

        cleared = self._clear_header_literals(working)
        changed |= cleared

        changed |= self._normalise_enums(working)
        changed |= self._pull_enums_from_nearby(working)

        if context and self._is_grand_total(working):
            changed |= context.inherit_codes(working)

        changed |= self._pad_codes(working)
        changed |= self._clean_financial_columns(working)
        changed |= self._infer_row_type(working)
        changed |= self._infer_row_level(working, context)

        issues.extend(self._validate(working, row_number))

        return RowResult(row_number=row_number, row=working, changed=changed, issues=issues)

    # -- alignment --------------------------------------------------------- #

    def _align_columns(
        self, row: List[str], row_number: int
    ) -> Tuple[List[str], bool, List[Issue]]:
        working = list(row)
        changed = False
        issues: List[Issue] = []
        original_len = len(working)

        removed_positions: List[int] = []
        while len(working) > self.expected_cols:
            drop_idx = self._preferred_drop_index(working)
            working.pop(drop_idx)
            removed_positions.append(drop_idx)
            changed = True

        if original_len > self.expected_cols and removed_positions:
            removed_tuple = tuple(sorted(removed_positions))
            message = (
                f"Row had {original_len} columns, expected {self.expected_cols}. "
                f"Removed empty fields at positions {removed_tuple}."
            )
            issues.append(
                Issue(
                    row_number=row_number,
                    column="ALL",
                    message=message,
                    code="EXTRA_COLUMNS_FIXED",
                    fixed=True,
                )
            )
        elif original_len > self.expected_cols:
            trimmed = original_len - self.expected_cols
            message = (
                f"Row had {original_len} columns, expected {self.expected_cols}. "
                f"Trimmed {trimmed} trailing field(s)."
            )
            issues.append(
                Issue(
                    row_number=row_number,
                    column="ALL",
                    message=message,
                    code="EXTRA_COLUMNS_FIXED",
                    fixed=True,
                )
            )

        if len(working) < self.expected_cols:
            deficit = self.expected_cols - len(working)
            working.extend([""] * deficit)
            changed = True
            message = (
                f"Row had {original_len} columns, expected {self.expected_cols}. "
                f"Padded {deficit} empty field(s) at end."
            )
            issues.append(
                Issue(
                    row_number=row_number,
                    column="ALL",
                    message=message,
                    code="MISSING_COLUMNS_FIXED",
                    fixed=True,
                )
            )

        return working, changed, issues

    @staticmethod
    def _preferred_drop_index(row: List[str]) -> int:
        for idx in reversed(range(len(row))):
            if not row[idx].strip():
                return idx
        return len(row) - 1

    # -- normalisation ---------------------------------------------------- #

    def _normalise_cells(self, row: List[str]) -> Tuple[List[str], bool]:
        cleaned: List[str] = []
        changed = False

        for cell in row:
            original = cell
            cleaned_cell = original.strip()
            if cleaned_cell == "...":
                cleaned_cell = ""
            if cleaned_cell != original:
                changed = True
            cleaned.append(cleaned_cell)

        return cleaned, changed

    def _normalise_enums(self, row: List[str]) -> bool:
        changed = False
        changed |= self._normalise_field(row, self.row_type_idx, ROW_TYPE_CANONICAL)
        changed |= self._normalise_field(row, self.row_level_idx, ROW_LEVEL_CANONICAL)
        changed |= self._normalise_field(row, self.vote_marker_idx, VOTE_CHARGE_CANONICAL)
        return changed

    def _clear_header_literals(self, row: List[str]) -> bool:
        changed = False
        for idx, cell in enumerate(row):
            if not cell:
                continue
            header = self.schema[idx]
            if cell.strip().lower() == header.lower():
                row[idx] = ""
                changed = True
        return changed

    def _normalise_field(
        self, row: List[str], idx: Optional[int], canonical_map: Dict[str, str]
    ) -> bool:
        if idx is None or idx >= len(row):
            return False
        value = row[idx]
        if not value:
            return False
        key = value.lower()
        canonical = canonical_map.get(key)
        if canonical and canonical != value:
            row[idx] = canonical
            return True
        return False

    def _pull_enums_from_nearby(self, row: List[str]) -> bool:
        changed = False
        changed |= self._pull_enum_from_nearby(row, self.row_type_idx, ROW_TYPE_CANONICAL)
        changed |= self._pull_enum_from_nearby(row, self.row_level_idx, ROW_LEVEL_CANONICAL)
        changed |= self._pull_enum_from_nearby(
            row, self.vote_marker_idx, VOTE_CHARGE_CANONICAL
        )
        return changed

    def _pull_enum_from_nearby(
        self,
        row: List[str],
        idx: Optional[int],
        canonical_map: Dict[str, str],
        window: int = 2,
    ) -> bool:
        if idx is None or idx >= len(row) or row[idx]:
            return False

        start = max(0, idx - window)
        end = min(len(row), idx + window + 1)

        for pos in range(start, end):
            if pos == idx or pos >= len(row):
                continue
            candidate = row[pos]
            if not candidate:
                continue
            canonical = canonical_map.get(candidate.lower())
            if canonical:
                row[idx] = canonical
                row[pos] = ""
                return True

        return False

    def _is_grand_total(self, row: List[str]) -> bool:
        if self.description_idx is None or self.description_idx >= len(row):
            return False
        description = row[self.description_idx].strip().upper()
        return description == "GRAND TOTAL"

    # -- enrichment -------------------------------------------------------- #

    def _pad_codes(self, row: List[str]) -> bool:
        changed = False
        for field, width in self.code_rules.items():
            idx = self.column_index.get(field)
            if idx is None or idx >= len(row):
                continue
            current = row[idx]
            padded = pad_code(current, width)
            if padded != current:
                row[idx] = padded
                changed = True
        return changed

    def _clean_financial_columns(self, row: List[str]) -> bool:
        changed = False
        for idx in self.financial_indices:
            if idx >= len(row):
                continue
            current = row[idx]
            cleaned = clean_financial_value(current)
            if cleaned != current:
                row[idx] = cleaned
                changed = True
        return changed

    def _infer_row_type(self, row: List[str]) -> bool:
        if self.row_type_idx is None or self.row_type_idx >= len(row):
            return False
        current = row[self.row_type_idx]
        if current in ROW_TYPE_VALUES:
            return False

        description = ""
        if self.description_idx is not None and self.description_idx < len(row):
            description = row[self.description_idx]

        if description and "total" in description.lower():
            row[self.row_type_idx] = "Total"
            return True

        has_numbers = any(
            row[idx] for idx in self.financial_indices if idx < len(row) and row[idx]
        )
        row[self.row_type_idx] = "Data" if has_numbers else "Header"
        return True

    def _infer_row_level(
        self, row: List[str], context: Optional[HierarchyContext]
    ) -> bool:
        if self.row_level_idx is None or self.row_level_idx >= len(row):
            return False

        current = row[self.row_level_idx]
        if current in ROW_LEVEL_VALUES:
            return False

        inferred = self._infer_level_from_codes(row)
        if inferred:
            row[self.row_level_idx] = inferred
            return True

        if context:
            inferred_from_context = context.infer_level()
            if inferred_from_context:
                row[self.row_level_idx] = inferred_from_context
                return True

        return False

    def _infer_level_from_codes(self, row: List[str]) -> str:
        for field, level in self.level_order:
            idx = self.column_index.get(field)
            if idx is None or idx >= len(row):
                continue
            if row[idx]:
                return level
        return ""

    # -- validation -------------------------------------------------------- #

    def _validate(self, row: List[str], row_number: int) -> List[Issue]:
        issues: List[Issue] = []

        row_type = row[self.row_type_idx] if self.row_type_idx is not None else ""
        if row_type not in ROW_TYPE_VALUES:
            issues.append(
                Issue(
                    row_number=row_number,
                    column="Row_Type",
                    message="Row_Type must be one of Data, Header, or Total",
                    code="ROW_TYPE_INVALID",
                )
            )

        row_level = row[self.row_level_idx] if self.row_level_idx is not None else ""
        if row_level not in ROW_LEVEL_VALUES:
            issues.append(
                Issue(
                    row_number=row_number,
                    column="Row_Level",
                    message="Row_Level must be a recognised hierarchy value",
                    code="ROW_LEVEL_INVALID",
                )
            )

        for field, width in self.code_rules.items():
            idx = self.column_index.get(field)
            if idx is None or idx >= len(row):
                continue
            value = row[idx]
            if not value:
                continue

            # Check if value contains non-numeric characters (except leading zeros)
            if not value.isdigit():
                issues.append(
                    Issue(
                        row_number=row_number,
                        column=field,
                        message=f"{field} contains non-numeric characters: '{value}'",
                        code=f"{field.upper()}_NON_NUMERIC",
                        fixed=False,
                    )
                )
                continue

            digits = re.sub(r"[^\d]", "", value)
            if len(digits) != width:
                issues.append(
                    Issue(
                        row_number=row_number,
                        column=field,
                        message=f"{field} should be {width} digits after padding, got {len(digits)}",
                        code=f"{field.upper()}_WIDTH",
                        fixed=False,
                    )
                )

        for idx in self.financial_indices:
            if idx is None or idx >= len(row):
                continue
            column = self.schema[idx]
            value = row[idx]
            if value and not NUMERIC_PATTERN.match(value):
                issues.append(
                    Issue(
                        row_number=row_number,
                        column=column,
                        message=f"{column} must contain numeric data or be blank",
                        code=f"{column.upper()}_NON_NUMERIC",
                    )
                )

        return issues


# --------------------------------------------------------------------------- #
# File and directory orchestration
# --------------------------------------------------------------------------- #

class CSVFileProcessor:
    """Read, clean, and write a single schema of CSV files."""

    def __init__(self, schema_name: str, schema: Sequence[str]):
        self.schema_name = schema_name
        self.schema = list(schema)
        self.row_processor = RowProcessor(schema_name, schema)

    def process_directory(
        self,
        input_dir: Path,
        output_dir: Path,
        csv_type: Optional[str] = None,
        logger: Optional[CleaningLogger] = None,
    ) -> List[FileReport]:
        csv_type_name = csv_type or self.schema_name
        csv_files = sorted(input_dir.glob("*.csv"))
        if not csv_files:
            print(f"  No CSV files found in {input_dir}")
            if logger:
                logger.append_text(f"No CSV files found in {input_dir}")
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        reports: List[FileReport] = []
        context = self.row_processor.create_context()

        for csv_file in csv_files:
            print(f"\nProcessing: {csv_file.name}")
            if logger:
                logger.append_text(f"Processing: {csv_file.name}")
            report = self.process_file(
                csv_file, output_dir / csv_file.name, context=context
            )
            reports.append(report)
            if logger:
                logger.record_file(csv_type_name, report)
            self._print_file_summary(csv_type_name, report, logger)

        self._print_directory_summary(csv_type_name, input_dir, reports, logger)

        # Record summary statistics
        if logger:
            logger.record_summary(csv_type_name, input_dir.name, reports)

        return reports


    def process_file(
        self,
        input_path: Path,
        output_path: Path,
        context: Optional[HierarchyContext] = None,
    ) -> FileReport:
        rows = self._read_rows(input_path)
        report = FileReport(input_file=input_path, output_file=output_path)

        if context is None:
            context = self.row_processor.create_context()

        if not rows:
            report.issues.append(
                Issue(
                    row_number=0,
                    column="FILE",
                    message="File is empty",
                    code="EMPTY_FILE",
                    fixed=False,
                )
            )
            return report

        header = rows[0]
        if header != self.schema:
            report.header_replaced = True
            header = list(self.schema)
            report.issues.append(
                Issue(
                    row_number=1,
                    column="HEADER",
                    message=f"Header replaced with expected schema ({self.schema_name})",
                    code="HEADER_REPLACED",
                    fixed=True,
                    severity="warning",
                )
            )

        cleaned_rows = [header]

        for row_number, raw_row in enumerate(rows[1:], start=2):
            if not any(cell.strip() for cell in raw_row):
                continue
            result = self.row_processor.process(raw_row, row_number, context)
            cleaned_rows.append(result.row)
            report.add_row(result)
            context.update(result.row)

        self._write_rows(output_path, cleaned_rows)
        return report

    def _read_rows(self, path: Path) -> List[List[str]]:
        with open(path, "r", encoding="utf-8", errors="ignore", newline="") as handle:
            lines = [line for line in handle if not line.strip().startswith("```")]
        reader = csv.reader(lines)
        return [row for row in reader]

    def _write_rows(self, path: Path, rows: List[List[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)

    @staticmethod
    def _print_file_summary(
        csv_type: str, report: FileReport, logger: Optional[CleaningLogger]
    ) -> None:
        rows_no_errors = report.rows_without_errors()
        rows_errors_corrected = report.rows_with_errors_corrected()
        rows_errors_uncorrected = report.rows_with_errors_uncorrected()

        print(f"  Total rows           : {report.cleaned_rows}")
        print(f"  Rows without errors  : {rows_no_errors}")
        print(f"  Rows with errors     : {report.rows_with_issues()}")
        print(f"    - Errors corrected : {rows_errors_corrected}")
        print(f"    - Errors uncorrected: {rows_errors_uncorrected}")

        if logger:
            logger.append_text(f"{csv_type} :: {report.input_file.name}")
            logger.append_text(f"  Total rows           : {report.cleaned_rows}")
            logger.append_text(f"  Rows without errors  : {rows_no_errors}")
            logger.append_text(f"  Rows with errors     : {report.rows_with_issues()}")
            logger.append_text(f"    - Errors corrected : {rows_errors_corrected}")
            logger.append_text(f"    - Errors uncorrected: {rows_errors_uncorrected}")

        if not report.issue_count:
            print("  ✅ No issues found")
            if logger:
                logger.append_text("  ✅ No issues found")
                logger.append_text("")
            return

        rows_with_issues = report.rows_with_issues()
        issues_by_row = report.issues_by_row()
        max_issues_in_row = (
            max(len(issues) for issues in issues_by_row.values()) if issues_by_row else 0
        )
        avg_issues = (
            round(report.issue_count / rows_with_issues, 2) if rows_with_issues else 0
        )

        print(f"  ⚠️  Total issues: {report.issue_count}")
        print(f"  ⚠️  Rows with issues: {rows_with_issues}")
        print(f"  ⚠️  Avg issues per row: {avg_issues}")
        print(f"  ⚠️  Max issues in a row: {max_issues_in_row}")
        if report.warnings_count():
            print(f"  ⚠️  Warnings: {report.warnings_count()}")

        if logger:
            logger.append_text(f"  ⚠️  Total issues: {report.issue_count}")
            logger.append_text(f"  ⚠️  Rows with issues: {rows_with_issues}")
            logger.append_text(f"  ⚠️  Avg issues per row: {avg_issues}")
            logger.append_text(f"  ⚠️  Max issues in a row: {max_issues_in_row}")
            if report.warnings_count():
                logger.append_text(f"  ⚠️  Warnings: {report.warnings_count()}")

        issue_breakdown = report.issue_counts_by_code()
        if issue_breakdown:
            print("\n  Issue breakdown by code:")
            for code, count in sorted(
                issue_breakdown.items(), key=lambda item: item[1], reverse=True
            ):
                print(f"    - {code}: {count}")

            if logger:
                logger.append_text("")
                logger.append_text("  Issue breakdown by code:")
                for code, count in sorted(
                    issue_breakdown.items(), key=lambda item: item[1], reverse=True
                ):
                    logger.append_text(f"    - {code}: {count}")

        print("\n  Example rows with issues:")
        for row_number in sorted(issues_by_row.keys())[:3]:
            print(f"    Row {row_number}:")
            for issue in issues_by_row[row_number][:3]:
                print(
                    f"      - [{issue.code}] {issue.column}: {issue.message}"
                    + (f" ({issue.severity})" if issue.severity != "error" else "")
                )

        if logger:
            logger.append_text("")
            logger.append_text("  Example rows with issues:")
            for row_number in sorted(issues_by_row.keys())[:3]:
                logger.append_text(f"    Row {row_number}:")
                for issue in issues_by_row[row_number][:3]:
                    suffix = (
                        f" ({issue.severity})" if issue.severity != "error" else ""
                    )
                    logger.append_text(
                        f"      - [{issue.code}] {issue.column}: {issue.message}{suffix}"
                    )
            logger.append_text("")

    @staticmethod
    def _print_directory_summary(
        csv_type: str,
        input_dir: Path,
        reports: List[FileReport],
        logger: Optional[CleaningLogger],
    ) -> None:
        if not reports:
            return

        total_rows = sum(r.cleaned_rows for r in reports)
        total_rows_without_errors = sum(r.rows_without_errors() for r in reports)
        total_rows_with_issues = sum(r.rows_with_issues() for r in reports)
        total_rows_errors_corrected = sum(r.rows_with_errors_corrected() for r in reports)
        total_rows_errors_uncorrected = sum(r.rows_with_errors_uncorrected() for r in reports)
        total_issues = sum(r.issue_count for r in reports)
        total_warnings = sum(r.warnings_count() for r in reports)
        aggregate_breakdown: Dict[str, int] = {}
        for report in reports:
            for code, count in report.issue_counts_by_code().items():
                aggregate_breakdown[code] = aggregate_breakdown.get(code, 0) + count

        print(f"\n  Summary for {input_dir.name}:")
        print(f"    files processed      : {len(reports)}")
        print(f"    total rows           : {total_rows}")
        print(f"    rows without errors  : {total_rows_without_errors}")
        print(f"    rows with errors     : {total_rows_with_issues}")
        print(f"      - errors corrected : {total_rows_errors_corrected}")
        print(f"      - errors uncorrected: {total_rows_errors_uncorrected}")
        print(f"    total issues         : {total_issues}")
        if total_warnings:
            print(f"    warnings             : {total_warnings}")
        if aggregate_breakdown:
            print("    issue breakdown      :")
            for code, count in sorted(
                aggregate_breakdown.items(), key=lambda item: item[1], reverse=True
            ):
                print(f"      - {code}: {count}")

        if logger:
            logger.append_text(f"Summary for {csv_type} ({input_dir.name}):")
            logger.append_text(f"  files processed      : {len(reports)}")
            logger.append_text(f"  total rows           : {total_rows}")
            logger.append_text(f"  rows without errors  : {total_rows_without_errors}")
            logger.append_text(f"  rows with errors     : {total_rows_with_issues}")
            logger.append_text(f"    - errors corrected : {total_rows_errors_corrected}")
            logger.append_text(f"    - errors uncorrected: {total_rows_errors_uncorrected}")
            logger.append_text(f"  total issues         : {total_issues}")
            if total_warnings:
                logger.append_text(f"  warnings             : {total_warnings}")
            if aggregate_breakdown:
                logger.append_text("  issue breakdown      :")
                for code, count in sorted(
                    aggregate_breakdown.items(), key=lambda item: item[1], reverse=True
                ):
                    logger.append_text(f"    - {code}: {count}")
            logger.append_text("")

# --------------------------------------------------------------------------- #
# Script entry point
# --------------------------------------------------------------------------- #

CSV_TYPE_CONFIG = [
    ("sub_major_head_summary_csv", "sub_major_head", SUB_MAJOR_HEAD_SCHEMA),
    ("minor_head_summary_csv", "minor_head", MINOR_HEAD_SCHEMA),
    ("sub_head_summary_csv", "sub_head", SUB_HEAD_SCHEMA),
    ("detailed_head_summary_csv", "detailed_head", DETAILED_HEAD_SCHEMA),
    ("object_head_summary_csv", "object_head", OBJECT_HEAD_SCHEMA),
]


def main() -> None:
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent
    output_base = project_root / "OUT" / "15_sr_ka_exp"

    csv_dir = output_base / "csv_outputs"
    cleaned_dir = output_base / "csv_cleaned"
    log_dir = output_base / "cleaning_logs"
    logger = CleaningLogger(log_dir)

    print("=" * 72)
    print("CSV CLEANUP")
    print("=" * 72)
    print(f"Root directory : {project_root}")
    print(f"Input location : {csv_dir}")
    print(f"Output location: {cleaned_dir}\n")

    logger.append_text("=" * 72)
    logger.append_text("CSV CLEANUP LOG")
    logger.append_text("=" * 72)
    logger.append_text(f"Root directory : {project_root}")
    logger.append_text(f"Input location : {csv_dir}")
    logger.append_text(f"Output location: {cleaned_dir}")
    logger.append_text("")

    overall_reports: List[FileReport] = []

    for folder, schema_name, schema in CSV_TYPE_CONFIG:
        input_dir = csv_dir / folder
        output_dir = cleaned_dir / folder

        print(f"Processing {schema_name.replace('_', ' ').title()} ({folder})")
        logger.append_text(f"Processing {schema_name} ({folder})")

        if not input_dir.exists():
            print(f"  Skipping: directory not found ({input_dir})\n")
            logger.append_text(f"  Skipping: directory not found ({input_dir})")
            logger.append_text("")
            continue

        processor = CSVFileProcessor(schema_name, schema)
        reports = processor.process_directory(
            input_dir, output_dir, schema_name, logger
        )
        overall_reports.extend(reports)
        print("")
        logger.append_text("")

    if overall_reports:
        total_files = len(overall_reports)
        total_rows = sum(r.cleaned_rows for r in overall_reports)
        total_rows_without_errors = sum(r.rows_without_errors() for r in overall_reports)
        total_rows_with_issues = sum(r.rows_with_issues() for r in overall_reports)
        total_rows_errors_corrected = sum(r.rows_with_errors_corrected() for r in overall_reports)
        total_rows_errors_uncorrected = sum(r.rows_with_errors_uncorrected() for r in overall_reports)
        total_issues = sum(r.issue_count for r in overall_reports)
        total_warnings = sum(r.warnings_count() for r in overall_reports)
        aggregate_breakdown: Dict[str, int] = {}
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
        if total_warnings:
            print(f"Warnings             : {total_warnings}")
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
        if total_warnings:
            logger.append_text(f"Warnings             : {total_warnings}")
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

    logger.save()

    print(f"\n📊 Logs saved to: {log_dir}")
    print(f"  - cleaning_report_{{timestamp}}.txt")
    print(f"  - cleaning_issues_{{timestamp}}.csv (row breakdown)")
    print(f"  - cleaning_issues_detailed_{{timestamp}}.csv")
    print(f"  - cleaning_summary_{{timestamp}}.csv (aggregated statistics)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
