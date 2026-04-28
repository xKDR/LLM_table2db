#!/usr/bin/env python3
"""Validation framework for Karnataka budget extraction.

Scope:
- In-schema checks inside object/minor/sub-major summary files.
- Across-schema checks between object -> minor/sub-major and minor -> sub-major.
- Detailed-head schema is intentionally skipped.

This is a local copy of SRC/26_ka_validation_sr/run_validation_sr.py with
clean output naming (no legacy numeric prefixes).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


NON_FINANCIAL_COLS = {
    "Source_Page_Number",
    "Volume_Number",
    "Demand_Number",
    "Major_Head_Code",
    "Major_Head_Name",
    "Sub_Major_Head_Code",
    "Sub_Major_Head_Name",
    "Minor_Head_Code",
    "Minor_Head_Name",
    "Sub_Head_Code",
    "Sub_Head_Name",
    "Detailed_Head_Code",
    "Detailed_Head_Name",
    "Object_Head_Code",
    "Object_Head_Description",
    "Full_Account_Code",
    "Description",
    "Vote_Charge_Marker",
    "Row_Type",
    "Row_Level",
}

CODE_WIDTHS = {
    "Major_Head_Code": 4,
    "Sub_Major_Head_Code": 2,
    "Minor_Head_Code": 3,
    "Sub_Head_Code": 1,
    "Detailed_Head_Code": 2,
    "Object_Head_Code": 3,
}


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    mode: str
    check_name: str
    source_file_key: str
    source_row_level: str
    source_row_type: str
    target_file_key: str
    target_row_level: str
    target_row_type: str
    key_cols: tuple[str, ...]


FILE_MAP = {
    "object_head": "final_object_head_summary.csv",
    "minor_head": "final_minor_head_summary.csv",
    "sub_major_head": "final_sub_major_head_summary.csv",
    "detailed_head": "final_detailed_head_summary.csv",
}


CHECKS: list[CheckSpec] = [
    # In-schema checks
    CheckSpec(
        "W01",
        "in_schema",
        "Object Data -> Minor Total (within object_head)",
        "object_head",
        "Object-Head",
        "Data",
        "object_head",
        "Minor-Head",
        "Total",
        ("Demand_Number", "Major_Head_Code", "Sub_Major_Head_Code", "Minor_Head_Code"),
    ),
    CheckSpec(
        "W02",
        "in_schema",
        "Object Data -> Sub-Major Total (within object_head)",
        "object_head",
        "Object-Head",
        "Data",
        "object_head",
        "Sub-Major-Head",
        "Total",
        ("Demand_Number", "Major_Head_Code", "Sub_Major_Head_Code"),
    ),
    CheckSpec(
        "W03",
        "in_schema",
        "Minor Data -> Minor Total (within minor_head)",
        "minor_head",
        "Minor-Head",
        "Data",
        "minor_head",
        "Minor-Head",
        "Total",
        ("Demand_Number", "Major_Head_Code", "Sub_Major_Head_Code", "Minor_Head_Code"),
    ),
    CheckSpec(
        "W04",
        "in_schema",
        "Minor Data -> Sub-Major Total (within minor_head)",
        "minor_head",
        "Minor-Head",
        "Data",
        "minor_head",
        "Sub-Major-Head",
        "Total",
        ("Demand_Number", "Major_Head_Code", "Sub_Major_Head_Code"),
    ),
    CheckSpec(
        "W05",
        "in_schema",
        "Sub-Major Data -> Sub-Major Total (within sub_major_head)",
        "sub_major_head",
        "Sub-Major-Head",
        "Data",
        "sub_major_head",
        "Sub-Major-Head",
        "Total",
        ("Demand_Number", "Major_Head_Code", "Sub_Major_Head_Code"),
    ),
    # In-schema checks for new FY documents (2023-24 onwards)
    # These documents have HOA Total (Detailed-Head) and Major-Head Total
    # but no Minor-Head or Sub-Major-Head summary totals.
    CheckSpec(
        "W06",
        "in_schema",
        "Object Data -> Detailed-Head Total (HOA Total) (within object_head)",
        "object_head",
        "Object-Head",
        "Data",
        "object_head",
        "Detailed-Head",
        "Total",
        ("Demand_Number", "Major_Head_Code", "Sub_Major_Head_Code", "Minor_Head_Code", "Sub_Head_Code", "Detailed_Head_Code"),
    ),
    CheckSpec(
        "W07",
        "in_schema",
        "Object Data -> Major-Head Total (within object_head)",
        "object_head",
        "Object-Head",
        "Data",
        "object_head",
        "Major-Head",
        "Total",
        ("Demand_Number", "Major_Head_Code"),
    ),
    # Across-schema checks
    CheckSpec(
        "A01",
        "across_schema",
        "Object Minor Total -> Minor Data",
        "object_head",
        "Minor-Head",
        "Total",
        "minor_head",
        "Minor-Head",
        "Data",
        ("Demand_Number", "Major_Head_Code", "Sub_Major_Head_Code", "Minor_Head_Code"),
    ),
    CheckSpec(
        "A02",
        "across_schema",
        "Object Sub-Major Total -> Sub-Major Data",
        "object_head",
        "Sub-Major-Head",
        "Total",
        "sub_major_head",
        "Sub-Major-Head",
        "Data",
        ("Demand_Number", "Major_Head_Code", "Sub_Major_Head_Code"),
    ),
    CheckSpec(
        "A03",
        "across_schema",
        "Minor Sub-Major Total -> Sub-Major Data",
        "minor_head",
        "Sub-Major-Head",
        "Total",
        "sub_major_head",
        "Sub-Major-Head",
        "Data",
        ("Demand_Number", "Major_Head_Code", "Sub_Major_Head_Code"),
    ),
]


def clean_str(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_code(value: Any, width: int) -> str:
    if pd.isna(value):
        return ""

    s: str
    if isinstance(value, int):
        s = str(value)
    elif isinstance(value, float):
        s = str(int(value)) if value.is_integer() else str(value)
    else:
        s = clean_str(value)

    if s.endswith(".0"):
        s = s[:-2]

    if not s:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return ""
    digits = digits[-width:]
    return digits.zfill(width)


def to_float(value: Any) -> float:
    if pd.isna(value):
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return 0.0


def calculate_accuracy(source_value: float, target_value: float) -> float:
    if target_value == 0:
        return 100.0 if source_value == 0 else 0.0
    abs_diff = abs(source_value - target_value)
    error_pct = (abs_diff / abs(target_value)) * 100.0
    return max(0.0, 100.0 - error_pct)


def infer_financial_cols(dfs: dict[str, pd.DataFrame]) -> list[str]:
    for df in dfs.values():
        cols = [
            c
            for c in df.columns
            if c not in NON_FINANCIAL_COLS and not c.endswith("__norm")
        ]
        if cols:
            return cols
    return []


def ensure_normalized_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    if "Demand_Number" in out.columns:
        out["Demand_Number__norm"] = out["Demand_Number"].apply(clean_str)
    else:
        out["Demand_Number__norm"] = ""

    for code_col, width in CODE_WIDTHS.items():
        norm_col = f"{code_col}__norm"
        if code_col in out.columns:
            out[norm_col] = out[code_col].apply(lambda x: normalize_code(x, width))
        else:
            out[norm_col] = ""

    out["Row_Type"] = out.get("Row_Type", "").fillna("").astype(str).str.strip()
    out["Row_Level"] = out.get("Row_Level", "").fillna("").astype(str).str.strip()

    return out


def key_norm_col(key_col: str) -> str:
    if key_col == "Demand_Number":
        return "Demand_Number__norm"
    if key_col in CODE_WIDTHS:
        return f"{key_col}__norm"
    return key_col


def prune_duplicate_totals(
    subset: pd.DataFrame, norm_key_cols: list[str], row_type: str
) -> pd.DataFrame:
    """Drop synthetic duplicate total rows (e.g., TOTAL V+C) for the same key."""
    if row_type != "Total" or subset.empty:
        return subset

    out = subset.copy()
    desc_series = out.get("Description", "").fillna("").astype(str).str.strip().str.upper()

    out = out[desc_series != "GRAND TOTAL"].copy()
    if out.empty:
        return out

    out["_desc_norm"] = out.get("Description", "").fillna("").astype(str).str.strip().str.upper()
    out["_marker_norm"] = (
        out.get("Vote_Charge_Marker", "").fillna("").astype(str).str.strip().str.upper()
    )

    dup_mask = out.duplicated(norm_key_cols, keep=False)
    if dup_mask.any():
        has_non_total_vc = out.groupby(norm_key_cols, dropna=False)["_desc_norm"].transform(
            lambda s: (s != "TOTAL V+C").any()
        )
        out = out[~(dup_mask & has_non_total_vc & (out["_desc_norm"] == "TOTAL V+C"))].copy()

        dup_mask = out.duplicated(norm_key_cols, keep=False)
        if dup_mask.any():
            has_non_vc_marker = out.groupby(norm_key_cols, dropna=False)["_marker_norm"].transform(
                lambda s: (s != "V+C").any()
            )
            out = out[~(dup_mask & has_non_vc_marker & (out["_marker_norm"] == "V+C"))].copy()

    return out.drop(columns=["_desc_norm", "_marker_norm"], errors="ignore")


def aggregate_rows(
    df: pd.DataFrame,
    row_level: str,
    row_type: str,
    key_cols: tuple[str, ...],
    financial_cols: list[str],
) -> dict[tuple[str, ...], dict[str, float]]:
    subset = df[(df["Row_Level"] == row_level) & (df["Row_Type"] == row_type)].copy()
    if subset.empty:
        return {}

    norm_key_cols = [key_norm_col(col) for col in key_cols]
    subset = prune_duplicate_totals(subset, norm_key_cols, row_type)
    if subset.empty:
        return {}

    grouped = (
        subset.groupby(norm_key_cols, dropna=False)[financial_cols]
        .sum(numeric_only=True)
        .reset_index()
    )

    output: dict[tuple[str, ...], dict[str, float]] = {}
    for _, row in grouped.iterrows():
        key = tuple(clean_str(row[col]) for col in norm_key_cols)
        output[key] = {col: float(row[col]) for col in financial_cols}

    return output


def compare_aggregates(
    volume: str,
    spec: CheckSpec,
    source_agg: dict[tuple[str, ...], dict[str, float]],
    target_agg: dict[tuple[str, ...], dict[str, float]],
    financial_cols: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    source_keys = set(source_agg.keys())
    target_keys = set(target_agg.keys())
    common_keys = sorted(source_keys & target_keys)

    rows: list[dict[str, Any]] = []

    total_abs_diff_by_col = {col: 0.0 for col in financial_cols}
    total_accuracy_sum_by_col = {col: 0.0 for col in financial_cols}
    total_accuracy_count_by_col = {col: 0 for col in financial_cols}

    passed = 0
    failed = 0

    for key in common_keys:
        row: dict[str, Any] = {
            "Volume": volume,
            "Validation_Mode": spec.mode,
            "Check_ID": spec.check_id,
            "Validation_Check": spec.check_name,
            "Source_File": FILE_MAP[spec.source_file_key],
            "Target_File": FILE_MAP[spec.target_file_key],
        }

        for idx, key_col in enumerate(spec.key_cols):
            row[key_col] = key[idx]

        all_match = True
        total_abs_diff = 0.0
        avg_accuracy_sum = 0.0

        for col in financial_cols:
            source_val = source_agg[key][col]
            target_val = target_agg[key][col]
            diff = source_val - target_val
            abs_diff = abs(diff)
            accuracy = calculate_accuracy(source_val, target_val)

            row[f"{col}_Source"] = round(source_val, 2)
            row[f"{col}_Target"] = round(target_val, 2)
            row[f"{col}_Diff"] = round(diff, 2)
            row[f"{col}_AbsDiff"] = round(abs_diff, 2)
            row[f"{col}_Accuracy_%"] = round(accuracy, 2)
            row[f"{col}_Match"] = "PASS" if abs_diff < 0.01 else "FAIL"

            if abs_diff >= 0.01:
                all_match = False

            total_abs_diff += abs_diff
            avg_accuracy_sum += accuracy

            total_abs_diff_by_col[col] += abs_diff
            total_accuracy_sum_by_col[col] += accuracy
            total_accuracy_count_by_col[col] += 1

        row["Total_AbsDiff"] = round(total_abs_diff, 2)
        row["Avg_Accuracy_%"] = round(avg_accuracy_sum / max(len(financial_cols), 1), 2)
        row["Status"] = "PASS" if all_match else "FAIL"

        if all_match:
            passed += 1
        else:
            failed += 1

        rows.append(row)

    details_df = pd.DataFrame(rows)

    compared = len(common_keys)
    nan = float("nan")
    pass_rate = round(passed / compared * 100.0, 2) if compared > 0 else nan

    src_count = len(source_keys)
    tgt_count = len(target_keys)

    summary: dict[str, Any] = {
        "Volume": volume,
        "Validation_Mode": spec.mode,
        "Check_ID": spec.check_id,
        "Validation_Check": spec.check_name,
        "Source_File": FILE_MAP[spec.source_file_key],
        "Source_Row_Level": spec.source_row_level,
        "Source_Row_Type": spec.source_row_type,
        "Target_File": FILE_MAP[spec.target_file_key],
        "Target_Row_Level": spec.target_row_level,
        "Target_Row_Type": spec.target_row_type,
        "Source_Key_Count": src_count,
        "Target_Key_Count": tgt_count,
        "Compared_Keys": compared,
        "Coverage_vs_Source_%": round(compared / src_count * 100.0, 2) if src_count > 0 else nan,
        "Coverage_vs_Target_%": round(compared / tgt_count * 100.0, 2) if tgt_count > 0 else nan,
        "Missing_In_Target": len(source_keys - target_keys),
        "Missing_In_Source": len(target_keys - source_keys),
        "Passed": passed,
        "Failed": failed,
        "Pass_Rate_%": pass_rate,
    }

    total_abs_all_cols = 0.0
    for col in financial_cols:
        total_abs = total_abs_diff_by_col[col]
        total_abs_all_cols += total_abs
        summary[f"{col}_Total_AbsDiff"] = round(total_abs, 2)

        acc_count = total_accuracy_count_by_col[col]
        if acc_count > 0:
            summary[f"{col}_Avg_Accuracy_%"] = round(
                total_accuracy_sum_by_col[col] / acc_count, 2
            )
        else:
            summary[f"{col}_Avg_Accuracy_%"] = nan

    summary["Total_AbsDiff_All_Columns"] = round(total_abs_all_cols, 2)

    if compared > 0 and not details_df.empty:
        summary["Overall_Avg_Accuracy_%"] = round(details_df["Avg_Accuracy_%"].mean(), 2)
    else:
        summary["Overall_Avg_Accuracy_%"] = nan

    return details_df, summary


def detect_delimiter(file_path: Path) -> str:
    """Return '|' if the file is pipe-delimited, ',' otherwise."""
    with open(file_path, "r", encoding="utf-8") as f:
        first_line = f.readline()
    return "|" if "|" in first_line else ","


def load_volume_data(volume_dir: Path) -> dict[str, pd.DataFrame]:
    loaded: dict[str, pd.DataFrame] = {}
    for key, filename in FILE_MAP.items():
        file_path = volume_dir / filename
        if not file_path.exists():
            continue
        sep = detect_delimiter(file_path)
        df = pd.read_csv(file_path, sep=sep)
        loaded[key] = ensure_normalized_cols(df)
    return loaded


def add_financial_numeric(df: pd.DataFrame, financial_cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in financial_cols:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = out[col].apply(to_float)
    return out


def run_volume_validation(volume_dir: Path, output_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    volume_name = volume_dir.name
    loaded = load_volume_data(volume_dir)
    if not loaded:
        return pd.DataFrame(), pd.DataFrame()

    financial_cols = infer_financial_cols(loaded)
    if not financial_cols:
        return pd.DataFrame(), pd.DataFrame()

    for key in list(loaded.keys()):
        loaded[key] = add_financial_numeric(loaded[key], financial_cols)

    output_dir.mkdir(parents=True, exist_ok=True)

    all_summaries: list[dict[str, Any]] = []
    all_details: list[pd.DataFrame] = []

    for spec in CHECKS:
        source_df = loaded.get(spec.source_file_key)
        target_df = loaded.get(spec.target_file_key)

        if source_df is None or target_df is None:
            nan = float("nan")
            summary = {
                "Volume": volume_name,
                "Validation_Mode": spec.mode,
                "Check_ID": spec.check_id,
                "Validation_Check": spec.check_name,
                "Source_File": FILE_MAP[spec.source_file_key],
                "Source_Row_Level": spec.source_row_level,
                "Source_Row_Type": spec.source_row_type,
                "Target_File": FILE_MAP[spec.target_file_key],
                "Target_Row_Level": spec.target_row_level,
                "Target_Row_Type": spec.target_row_type,
                "Source_Key_Count": 0,
                "Target_Key_Count": 0,
                "Compared_Keys": 0,
                "Coverage_vs_Source_%": nan,
                "Coverage_vs_Target_%": nan,
                "Missing_In_Target": 0,
                "Missing_In_Source": 0,
                "Passed": 0,
                "Failed": 0,
                "Pass_Rate_%": nan,
                "Total_AbsDiff_All_Columns": 0.0,
                "Overall_Avg_Accuracy_%": nan,
            }
            for col in financial_cols:
                summary[f"{col}_Total_AbsDiff"] = 0.0
                summary[f"{col}_Avg_Accuracy_%"] = nan
            all_summaries.append(summary)
            continue

        source_agg = aggregate_rows(
            source_df,
            spec.source_row_level,
            spec.source_row_type,
            spec.key_cols,
            financial_cols,
        )
        target_agg = aggregate_rows(
            target_df,
            spec.target_row_level,
            spec.target_row_type,
            spec.key_cols,
            financial_cols,
        )

        details_df, summary = compare_aggregates(
            volume_name,
            spec,
            source_agg,
            target_agg,
            financial_cols,
        )
        all_summaries.append(summary)

        if not details_df.empty:
            detail_filename = f"{spec.mode}_{spec.check_id}_{spec.check_name.lower().replace(' ', '_').replace('->', 'to').replace('-', '_').replace('(', '').replace(')', '')}.csv"
            details_df.to_csv(output_dir / detail_filename, index=False)
            all_details.append(details_df)

    summary_df = pd.DataFrame(all_summaries)

    within_df = summary_df[summary_df["Validation_Mode"] == "in_schema"].copy()
    across_df = summary_df[summary_df["Validation_Mode"] == "across_schema"].copy()

    within_df.to_csv(output_dir / "in_schema_summary.csv", index=False)
    across_df.to_csv(output_dir / "across_schema_summary.csv", index=False)
    summary_df.to_csv(output_dir / "validation_summary.csv", index=False)

    details_combined = pd.concat(all_details, ignore_index=True) if all_details else pd.DataFrame()
    if not details_combined.empty:
        details_combined.to_csv(output_dir / "validation_details_all_checks.csv", index=False)

    return summary_df, details_combined


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "(no rows)"

    headers = [str(c) for c in df.columns]
    rows = [[str(v) for v in row] for row in df.itertuples(index=False, name=None)]
    all_rows = [headers] + rows
    widths = [max(len(r[i]) for r in all_rows) for i in range(len(headers))]

    def fmt(row: list[str]) -> str:
        cells = [row[i].ljust(widths[i]) for i in range(len(row))]
        return "| " + " | ".join(cells) + " |"

    separator = "| " + " | ".join("-" * w for w in widths) + " |"
    lines = [fmt(headers), separator]
    lines.extend(fmt(row) for row in rows)
    return "\n".join(lines)


def write_final_report(
    output_base: Path,
    combined_summary: pd.DataFrame,
    processed_volumes: list[str],
    input_base: Path,
) -> None:
    report_path = output_base / "validation_report.md"

    if combined_summary.empty:
        report_path.write_text(
            "# Validation Report\n\nNo validation summaries were generated.\n",
            encoding="utf-8",
        )
        return

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")

    mode_summary = (
        combined_summary.groupby("Validation_Mode")[["Compared_Keys", "Passed", "Failed"]]
        .sum()
        .reset_index()
    )
    mode_summary["Pass_Rate_%"] = mode_summary.apply(
        lambda r: round((r["Passed"] / r["Compared_Keys"] * 100.0), 2)
        if r["Compared_Keys"] > 0
        else float("nan"),
        axis=1,
    )

    check_summary = (
        combined_summary.groupby(["Validation_Mode", "Check_ID", "Validation_Check"])[
            ["Compared_Keys", "Passed", "Failed", "Pass_Rate_%"]
        ]
        .mean(numeric_only=True)
        .reset_index()
        .sort_values(["Validation_Mode", "Check_ID"])
    )

    low_pass = combined_summary[combined_summary["Compared_Keys"] > 0].copy()
    low_pass = low_pass.sort_values("Pass_Rate_%").head(20)

    lines = [
        "# Validation Report",
        "",
        "## Run Metadata",
        f"- Generated At (UTC): {now_utc}",
        f"- Input Base: `{input_base}`",
        f"- Output Base: `{output_base}`",
        f"- Processed Volumes: {len(processed_volumes)}",
        "",
        "## Coverage",
        f"- Volume list: {', '.join(processed_volumes)}",
        "",
        "## Overall Mode-Level Results",
        dataframe_to_markdown(mode_summary),
        "",
        "## Check-Level Average Results (Across Volumes)",
        dataframe_to_markdown(check_summary),
        "",
        "## Lowest Pass-Rate Volume Checks (Top 20)",
    ]

    if low_pass.empty:
        lines.append("- No comparable keys were found in any check.")
    else:
        lines.append(
            dataframe_to_markdown(
                low_pass[
                    [
                        "Volume",
                        "Validation_Mode",
                        "Check_ID",
                        "Validation_Check",
                        "Compared_Keys",
                        "Passed",
                        "Failed",
                        "Pass_Rate_%",
                    ]
                ]
            )
        )

    lines.extend(
        [
            "",
            "## Output Files",
            "- `validation_summary.csv`",
            "- Per-volume detailed CSVs under `volumes/<volume>/`",
        ]
    )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_all(input_base: Path, output_base: Path) -> None:
    volume_dirs = sorted([p for p in input_base.iterdir() if p.is_dir()])
    output_base.mkdir(parents=True, exist_ok=True)

    processed: list[str] = []
    all_summary_frames: list[pd.DataFrame] = []

    for volume_dir in volume_dirs:
        volume_output = output_base / "volumes" / volume_dir.name
        summary_df, _ = run_volume_validation(volume_dir, volume_output)
        if summary_df.empty:
            continue
        if summary_df["Compared_Keys"].sum() == 0:
            continue

        processed.append(volume_dir.name)
        all_summary_frames.append(summary_df)

    if all_summary_frames:
        combined = pd.concat(all_summary_frames, ignore_index=True)
        combined = combined[combined["Compared_Keys"] > 0].reset_index(drop=True)
        combined.to_csv(output_base / "validation_summary.csv", index=False)
    else:
        combined = pd.DataFrame()

    write_final_report(output_base, combined, processed, input_base)

    print(f"Processed volumes: {len(processed)}")
    print(f"Output base: {output_base}")
    if not combined.empty:
        print(f"Combined summary rows: {len(combined)}")
        by_mode = combined["Validation_Mode"].value_counts().to_dict()
        print(f"Rows by mode: {by_mode}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="run_validation",
        description="Run KA in-schema/across-schema validation",
    )
    parser.add_argument(
        "--input-base",
        required=True,
        help="Input base directory containing per-volume outputs",
    )
    parser.add_argument(
        "--output-base",
        required=True,
        help="Output base directory for validation artifacts",
    )
    parser.add_argument(
        "--volume",
        default=None,
        help="Optional single volume name to process (e.g., 2020-21_expvol_7)",
    )
    args = parser.parse_args()

    input_base = Path(args.input_base)
    output_base = Path(args.output_base)

    if args.volume:
        volume_dir = input_base / args.volume
        volume_output = output_base / "volumes" / args.volume
        summary_df, _ = run_volume_validation(volume_dir, volume_output)

        if summary_df.empty:
            print(f"No validation results for volume: {args.volume}")
            return

        summary_df.to_csv(output_base / "validation_summary.csv", index=False)
        write_final_report(output_base, summary_df, [args.volume], input_base)
        print(f"Processed single volume: {args.volume}")
        print(f"Output: {volume_output}")
        return

    run_all(input_base, output_base)


if __name__ == "__main__":
    main()
