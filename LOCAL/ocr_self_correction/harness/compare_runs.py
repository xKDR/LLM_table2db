#!/usr/bin/env python3
"""Compare two validation summary CSVs and produce a delta report.

Usage:
    python compare_runs.py \
        --run-a outputs/runs/R1/validation/validation_summary.csv \
        --run-b outputs/runs/R2/validation/validation_summary.csv
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd


HIGHLIGHT_CHECKS = {"W02", "A02"}

METRIC_COLS = ["Compared_Keys", "Passed", "Failed", "Pass_Rate_%", "Overall_Avg_Accuracy_%"]


def load_and_agg(path: str) -> pd.DataFrame:
    """Load a multi-volume validation summary and aggregate per check.

    Accuracy is computed as a weighted mean (weighted by Compared_Keys),
    per methodology.  Rows with Compared_Keys=0 are excluded from the
    accuracy calculation.
    """
    df = pd.read_csv(path)

    def _agg_check(g: pd.DataFrame) -> pd.Series:
        keys = g["Compared_Keys"].sum()
        passed = g["Passed"].sum()
        failed = g["Failed"].sum()
        valid = g[g["Compared_Keys"] > 0]
        if keys > 0 and not valid.empty:
            w_acc = (valid["Overall_Avg_Accuracy_%"] * valid["Compared_Keys"]).sum() / keys
        else:
            w_acc = float("nan")
        return pd.Series({
            "Compared_Keys": keys,
            "Passed": passed,
            "Failed": failed,
            "Overall_Avg_Accuracy_%": round(w_acc, 2),
        })

    agg = df.groupby(["Check_ID", "Validation_Check"]).apply(
        _agg_check, include_groups=False
    ).reset_index()
    agg["Pass_Rate_%"] = agg.apply(
        lambda r: round(r["Passed"] / r["Compared_Keys"] * 100, 2)
        if r["Compared_Keys"] > 0
        else float("nan"),
        axis=1,
    )
    return agg


def weighted_accuracy(df: pd.DataFrame) -> float:
    """Compute weighted accuracy across all checks (weighted by Compared_Keys).

    Only rows with Compared_Keys > 0 are included, per methodology.
    """
    mask = df["Compared_Keys"] > 0
    valid = df.loc[mask]
    total_keys = valid["Compared_Keys"].sum()
    if total_keys == 0:
        return float("nan")
    weighted = (valid["Overall_Avg_Accuracy_%"] * valid["Compared_Keys"]).sum()
    return round(weighted / total_keys, 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two validation runs")
    parser.add_argument("--run-a", required=True, help="Path to run A summary CSV (baseline)")
    parser.add_argument("--run-b", required=True, help="Path to run B summary CSV (new run)")
    parser.add_argument("--label-a", default="Run A", help="Label for run A")
    parser.add_argument("--label-b", default="Run B", help="Label for run B")
    args = parser.parse_args()

    agg_a = load_and_agg(args.run_a)
    agg_b = load_and_agg(args.run_b)

    merged = agg_a.merge(
        agg_b,
        on=["Check_ID", "Validation_Check"],
        suffixes=("_A", "_B"),
        how="outer",
    ).fillna(0)

    merged["Pass_Rate_Delta"] = (merged["Pass_Rate_%_B"] - merged["Pass_Rate_%_A"]).round(2)
    merged["Accuracy_Delta"] = (
        merged["Overall_Avg_Accuracy_%_B"] - merged["Overall_Avg_Accuracy_%_A"]
    ).round(2)
    merged["Keys_Delta"] = merged["Compared_Keys_B"] - merged["Compared_Keys_A"]
    merged["Regression"] = merged["Pass_Rate_Delta"] < 0

    wa_a = weighted_accuracy(agg_a)
    wa_b = weighted_accuracy(agg_b)

    # --- Output ---
    lines = [
        f"# Run Comparison: {args.label_a} vs {args.label_b}",
        "",
        f"- {args.label_a}: `{args.run_a}`",
        f"- {args.label_b}: `{args.run_b}`",
        "",
        "## Overall Weighted Accuracy",
        "",
        f"| Metric | {args.label_a} | {args.label_b} | Delta |",
        f"|--------|{'-' * len(args.label_a)}--|{'-' * len(args.label_b)}--|-------|",
        f"| Weighted Accuracy | {wa_a} | {wa_b} | {round(wa_b - wa_a, 2)} |",
        "",
        "## Per-Check Deltas",
        "",
        "| Check | Name | Keys_A | Keys_B | PassRate_A | PassRate_B | PR_Delta | Acc_A | Acc_B | Acc_Delta | Regress? |",
        "|-------|------|--------|--------|------------|------------|----------|-------|-------|-----------|----------|",
    ]

    for _, r in merged.sort_values("Check_ID").iterrows():
        flag = "YES" if r["Regression"] else ""
        marker = " **" if r["Check_ID"] in HIGHLIGHT_CHECKS else ""
        end_marker = "**" if marker else ""
        lines.append(
            f"| {marker}{r['Check_ID']}{end_marker} | {r['Validation_Check']} "
            f"| {int(r['Compared_Keys_A'])} | {int(r['Compared_Keys_B'])} "
            f"| {r['Pass_Rate_%_A']} | {r['Pass_Rate_%_B']} | {r['Pass_Rate_Delta']} "
            f"| {r['Overall_Avg_Accuracy_%_A']} | {r['Overall_Avg_Accuracy_%_B']} "
            f"| {r['Accuracy_Delta']} | {flag} |"
        )

    # Highlight W02 / A02 specifically
    highlight_rows = merged[merged["Check_ID"].isin(HIGHLIGHT_CHECKS)]
    if not highlight_rows.empty:
        lines.extend(["", "## W02 / A02 Focus"])
        for _, r in highlight_rows.iterrows():
            direction = "improved" if r["Pass_Rate_Delta"] > 0 else "regressed" if r["Pass_Rate_Delta"] < 0 else "unchanged"
            lines.append(
                f"- **{r['Check_ID']}**: Pass rate {r['Pass_Rate_%_A']}% -> {r['Pass_Rate_%_B']}% ({direction}, delta={r['Pass_Rate_Delta']}pp)"
            )

    # Regression summary
    regressions = merged[merged["Regression"]]
    if not regressions.empty:
        lines.extend(["", "## Regressions"])
        for _, r in regressions.iterrows():
            lines.append(
                f"- **{r['Check_ID']}** ({r['Validation_Check']}): "
                f"pass rate dropped {abs(r['Pass_Rate_Delta'])}pp"
            )
    else:
        lines.extend(["", "## Regressions", "", "None detected."])

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
