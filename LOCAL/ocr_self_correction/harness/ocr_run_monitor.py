#!/usr/bin/env python3
"""OCR Pipeline Live Tracker — auto-attaches to running pipeline processes.

Launches, finds whatever run_snippet_baseline.py is running, and live-
tracks it: stage progress, log tail, errors, metrics.  Stays alive
until the process exits (or Ctrl-C).

Usage:
    python ocr_run_monitor.py              # auto-attach to running process
    python ocr_run_monitor.py --run-id R1  # track specific run
    python ocr_run_monitor.py --snapshot   # one-shot snapshot (old behavior)
    python ocr_run_monitor.py --list       # list runs
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
SELF_CORR = REPO_ROOT / "LOCAL" / "ocr_self_correction"
RUNS_DIR = SELF_CORR / "outputs" / "runs"
MANIFEST = SELF_CORR / "manifests" / "snippet_manifest.csv"

# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

STAGES = [
    ("metadata", "Meta"),
    ("images", "PDF\u2192Img"),
    ("extraction", "Gemini"),
    ("cleaning", "Clean"),
    ("combining", "Combine"),
    ("validation", "Validate"),
]

STAGE_KEYS = [s[0] for s in STAGES]
CHECK_ORDER = ["W01", "W02", "W03", "W04", "W05", "A01", "A02", "A03"]

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

C_OK = "bright_green"
C_WARN = "bright_yellow"
C_ERR = "bright_red"
C_DIM = "grey50"
C_ACCENT = "medium_purple1"
C_GOLD = "gold1"
C_TEAL = "dark_turquoise"
C_ORANGE = "dark_orange"
C_PINK = "hot_pink"
C_BLUE = "cornflower_blue"

console = Console()

# ---------------------------------------------------------------------------
# Process discovery
# ---------------------------------------------------------------------------

def find_pipeline_processes() -> List[Dict[str, Any]]:
    """Scan ps for any run_snippet_baseline.py processes."""
    procs: List[Dict[str, Any]] = []
    try:
        out = subprocess.check_output(
            ["ps", "aux"], text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            if "run_snippet_baseline.py" not in line:
                continue
            if "grep" in line or "ps aux" in line:
                continue
            parts = line.split()
            pid = int(parts[1])
            # Extract args from command line
            cmd = " ".join(parts[10:])
            run_id = None
            out_root = None
            # Parse --run-id
            m = re.search(r"--run-id\s+(\S+)", cmd)
            if m:
                run_id = m.group(1)
            # Parse --out-root
            m = re.search(r"--out-root\s+(\S+)", cmd)
            if m:
                out_root = m.group(1)
            procs.append({
                "pid": pid,
                "run_id": run_id,
                "out_root": out_root,
                "cmd": cmd,
                "user": parts[0],
                "cpu": parts[2],
                "mem": parts[3],
                "started": parts[8],
            })
    except Exception:
        pass
    return procs


def pid_alive(pid: int) -> bool:
    """Check if a PID is still alive."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def resolve_run_dir(proc: Dict[str, Any]) -> Optional[Path]:
    """Resolve the run output directory from process info."""
    if proc.get("out_root"):
        p = Path(proc["out_root"])
        if p.is_absolute():
            return p
        return REPO_ROOT / p
    if proc.get("run_id"):
        return RUNS_DIR / proc["run_id"]
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_manifest() -> List[Dict[str, str]]:
    if not MANIFEST.exists():
        return []
    with MANIFEST.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def volume_slug(row: Dict[str, str]) -> str:
    return f"{row['year']}_{row['volume']}"


def list_runs() -> List[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted(
        d.name for d in RUNS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )


def is_baseline_only(run_dir: Path) -> bool:
    has_val = (run_dir / "validation_summary.csv").exists()
    has_volumes = any(
        (d / "run_metadata.json").exists()
        for d in run_dir.iterdir() if d.is_dir()
    )
    return has_val and not has_volumes


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

LOG_RE = {
    "images_start": re.compile(r"Starting extract_pdf_to_images"),
    "images_done": re.compile(r"Completed extract_pdf_to_images in ([\d.]+)"),
    "extraction_start": re.compile(r"Starting extract_data_with_gemini"),
    "extraction_done": re.compile(r"Completed extract_data_with_gemini in ([\d.]+)"),
    "cleaning_start": re.compile(r"Starting run_csv_cleaner"),
    "cleaning_done": re.compile(r"Completed run_csv_cleaner in ([\d.]+)"),
    "combining_start": re.compile(r"Starting run_csv_combiner"),
    "combining_done": re.compile(r"Completed run_csv_combiner in ([\d.]+)"),
    "page_processing": re.compile(r"Processing page (\d+)/(\d+)"),
    "api_fail": re.compile(r"generate_content failed \(attempt (\d+)/(\d+)\): (.+)"),
    "api_fatal": re.compile(r"Gemini API call failed after (\d+) attempts"),
    "log_init": re.compile(r"Logging initialized\. Log file: (.+)"),
}


def parse_logs(run_dir: Path) -> Tuple[Dict[str, Any], List[str]]:
    """Parse all logs. Returns (per_volume_progress, recent_lines)."""
    log_files = sorted(run_dir.glob("*/runtime_log/workflow_execution_*.log"))

    all_lines: List[str] = []
    for lf in log_files:
        try:
            text = lf.read_text(encoding="utf-8", errors="replace")
            if text.strip():
                all_lines.extend(text.splitlines())
        except Exception:
            pass

    progress: Dict[str, Dict[str, Any]] = {}
    current_vol = None

    def get_vp(vol: str) -> Dict[str, Any]:
        if vol not in progress:
            progress[vol] = {
                "stages_done": [],
                "stage_active": None,
                "pages_total": 0,
                "pages_done": 0,
                "pages_failed": 0,
                "api_retries": 0,
                "last_error": None,
                "timings": {},
            }
        return progress[vol]

    for line in all_lines:
        m = LOG_RE["log_init"].search(line)
        if m:
            parts = Path(m.group(1)).parts
            for i, p in enumerate(parts):
                if p == "runs" and i + 2 < len(parts):
                    current_vol = parts[i + 2]
                    break
            continue

        if current_vol is None and log_files:
            parts = log_files[0].parts
            for i, p in enumerate(parts):
                if p == "runs" and i + 2 < len(parts):
                    current_vol = parts[i + 2]
                    break

        if current_vol is None:
            continue

        vp = get_vp(current_vol)

        for sk in ["images", "extraction", "cleaning", "combining"]:
            if LOG_RE[f"{sk}_start"].search(line):
                vp["stage_active"] = sk
                break
            dm = LOG_RE[f"{sk}_done"].search(line)
            if dm:
                if sk not in vp["stages_done"]:
                    vp["stages_done"].append(sk)
                vp["timings"][sk] = float(dm.group(1))
                vp["stage_active"] = None
                break

        pm = LOG_RE["page_processing"].search(line)
        if pm:
            vp["pages_total"] = int(pm.group(2))
            vp["pages_done"] = max(vp["pages_done"], int(pm.group(1)) - 1)

        am = LOG_RE["api_fail"].search(line)
        if am:
            vp["api_retries"] += 1
            vp["last_error"] = am.group(3)[:100]

        fm = LOG_RE["api_fatal"].search(line)
        if fm:
            vp["pages_failed"] += 1
            vp["pages_done"] += 1

    # Last N lines for live tail (skip blank lines)
    tail_lines = [l for l in all_lines[-25:] if l.strip()]

    return progress, tail_lines


def detect_fs_stages(run_dir: Path, slug: str) -> Dict[str, str]:
    vol = run_dir / slug
    if not vol.exists():
        return {s: "pending" for s in STAGE_KEYS}
    st: Dict[str, str] = {}
    st["metadata"] = "done" if (vol / "run_metadata.json").exists() else "pending"
    img = vol / "images"
    st["images"] = "done" if (img.exists() and list(img.glob("*.jpg"))) else "pending"
    jd = vol / "json_outputs"
    st["extraction"] = (
        "done" if (jd.exists() and list(jd.glob("*.json")))
        else "failed" if jd.exists()
        else "pending"
    )
    cd = vol / "cleaning_logs"
    if cd.exists() and list(cd.glob("cleaning_report_*.txt")):
        csv_d = vol / "csv_outputs"
        has = any(
            sub.is_dir() and list(sub.glob("*.csv"))
            for sub in csv_d.iterdir()
        ) if csv_d.exists() else False
        st["cleaning"] = "done" if has else "empty"
    else:
        st["cleaning"] = "pending"
    st["combining"] = "done" if list(vol.glob("final_*.csv")) else "pending"
    st["validation"] = "done" if (run_dir / "validation" / "validation_summary.csv").exists() else "pending"
    return st


# ---------------------------------------------------------------------------
# Validation metrics
# ---------------------------------------------------------------------------

def load_validation(csv_path: Path) -> Dict[str, Dict[str, Any]]:
    if not csv_path.exists():
        return {}
    metrics: Dict[str, Dict[str, Any]] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            ck = row.get("Check_ID", "")
            if not ck:
                continue
            if ck not in metrics:
                metrics[ck] = {"keys": 0, "passed": 0, "acc_sum": 0.0, "acc_n": 0}
            m = metrics[ck]
            n = int(row.get("Compared_Keys", 0) or 0)
            m["keys"] += n
            m["passed"] += int(row.get("Passed", 0) or 0)
            a = row.get("Overall_Avg_Accuracy_%", "")
            if a and n > 0:
                m["acc_sum"] += float(a) * n
                m["acc_n"] += n
    for m in metrics.values():
        m["pass_pct"] = (m["passed"] / m["keys"] * 100) if m["keys"] > 0 else 0.0
        m["acc_pct"] = (m["acc_sum"] / m["acc_n"]) if m["acc_n"] > 0 else 0.0
    return metrics


def w_accuracy(metrics: Dict[str, Dict[str, Any]]) -> float:
    s = sum(m["acc_sum"] for m in metrics.values() if m["acc_n"] > 0)
    n = sum(m["acc_n"] for m in metrics.values() if m["acc_n"] > 0)
    return s / n if n > 0 else 0.0


# ---------------------------------------------------------------------------
# Visual components
# ---------------------------------------------------------------------------

BANNER = r"""
  ___   ___ ___   __  __          _ _
 / _ \ / __| _ \ |  \/  |___ _ _ (_) |_ ___ _ _
| (_) | (__|   / | |\/| / _ \ ' \| |  _/ _ \ '_|
 \___/ \___|_|_\ |_|  |_\___/_||_|_|\__\___/_|
"""


def mk_banner() -> Text:
    colors = ["bright_cyan", "dodger_blue2", "medium_purple1", "hot_pink"]
    t = Text()
    for i, line in enumerate(BANNER.strip("\n").splitlines()):
        t.append(line + "\n", style=f"bold {colors[i % len(colors)]}")
    return t


def bar(val: float, w: int = 16) -> Text:
    ratio = min(val / 100.0, 1.0)
    filled = int(ratio * w)
    c = (
        "bright_green" if val >= 95
        else "bright_yellow" if val >= 80
        else "dark_orange" if val >= 50
        else "bright_red"
    )
    t = Text()
    t.append("\u2588" * filled, style=c)
    t.append("\u2591" * (w - filled), style="grey30")
    t.append(f" {val:.1f}%", style=f"bold {c}")
    return t


def badge(status: str) -> Text:
    return {
        "done":    Text(" \u2714 DONE ", style="bold white on green"),
        "running": Text(" \u25b6 RUN  ", style="bold white on dark_orange"),
        "failed":  Text(" \u2718 FAIL ", style="bold white on red"),
        "empty":   Text(" \u25cb VOID ", style="bold black on bright_yellow"),
        "pending": Text("  \u00b7\u00b7\u00b7  ", style="grey42"),
    }.get(status, Text("  \u00b7\u00b7\u00b7  ", style="grey42"))


def vol_label(slug: str) -> Text:
    parts = slug.split("_", 1)
    t = Text()
    t.append(parts[0], style=f"bold {C_TEAL}")
    if len(parts) > 1:
        t.append("_", style="grey50")
        t.append(parts[1], style=f"bold {C_ACCENT}")
    return t


# ---------------------------------------------------------------------------
# Dashboard builder
# ---------------------------------------------------------------------------

def build_dashboard(
    run_dir: Path,
    run_id: str,
    proc: Optional[Dict[str, Any]],
    tick: int,
) -> Group:
    manifest = read_manifest()
    is_alive = proc is not None and pid_alive(proc["pid"])
    log_progress, tail = parse_logs(run_dir)

    panels: list = []

    # ── Header ──────────────────────────────────────────────────────────
    info = Table.grid(padding=(0, 3))
    info.add_column(style=f"bold {C_TEAL}", justify="right", min_width=10)
    info.add_column(min_width=50)

    # Read metadata
    meta = {}
    for d in sorted(run_dir.iterdir()):
        mf = d / "run_metadata.json"
        if mf.exists():
            with mf.open() as f:
                meta = json.load(f)
            break

    baseline_only = is_baseline_only(run_dir) if run_dir.exists() else False

    st = Text()
    if baseline_only:
        st.append(" \u2605 BASELINE ", style="bold bright_white on dodger_blue2")
    elif is_alive:
        # Spinner chars
        spinner = ["\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f"]
        sp = spinner[tick % len(spinner)]
        st.append(f" {sp} LIVE ", style="bold bright_white on green")
        st.append(f"  PID {proc['pid']}", style=f"bold {C_OK}")
        st.append(f"  CPU {proc.get('cpu', '?')}%  MEM {proc.get('mem', '?')}%", style=C_DIM)
    else:
        st.append(" \u25cf FINISHED ", style="bold bright_white on grey50")

    info.add_row("Run", Text(run_id, style="bold bright_white underline"))
    info.add_row("Status", st)
    if not baseline_only:
        info.add_row("Model", Text(meta.get("model", "?"), style=f"bold {C_GOLD}"))
        ts = meta.get("timestamp", "")
        if ts and is_alive:
            try:
                started = datetime.fromisoformat(ts)
                elapsed = datetime.now(timezone.utc) - started
                mins = int(elapsed.total_seconds() // 60)
                secs = int(elapsed.total_seconds() % 60)
                info.add_row("Elapsed", Text(f"{mins}m {secs}s", style=f"bold {C_WARN}"))
            except Exception:
                pass
    else:
        info.add_row("Source", Text("OUT/27_KA_SR_run_minor", style=f"bold {C_GOLD}"))

    panels.append(Panel(
        Group(Align.center(mk_banner()), Text(""), info),
        border_style="bright_cyan", padding=(1, 3),
    ))

    # ── Pipeline table (skip for baseline) ──────────────────────────────
    if not baseline_only:
        tbl = Table(
            box=box.HEAVY_HEAD, header_style="bold bright_white",
            border_style=C_BLUE, row_styles=["", "on grey7"],
            pad_edge=True, expand=True,
        )
        tbl.add_column("Volume", min_width=20)
        tbl.add_column("Pg", justify="center", min_width=3, style=f"bold {C_TEAL}")
        for _, label in STAGES:
            tbl.add_column(label, justify="center", min_width=9)
        tbl.add_column("Detail", min_width=20)

        done_count = 0
        fail_count = 0

        for row in manifest:
            slug = volume_slug(row)
            fs = detect_fs_stages(run_dir, slug)
            lp = log_progress.get(slug, {})

            statuses = {}
            for sk, _ in STAGES:
                fss = fs.get(sk, "pending")
                if lp.get("stage_active") == sk and is_alive:
                    statuses[sk] = "running"
                elif sk in lp.get("stages_done", []):
                    statuses[sk] = "done"
                else:
                    statuses[sk] = fss

            # Detail column: what's happening right now on this volume
            detail = Text()
            if lp.get("stage_active") == "extraction" and is_alive:
                pg_done = lp.get("pages_done", 0)
                pg_total = lp.get("pages_total", 0)
                retries = lp.get("api_retries", 0)
                if pg_total > 0:
                    detail.append(f"pg {pg_done}/{pg_total}", style=f"bold {C_WARN}")
                if retries > 0:
                    detail.append(f" ({retries} retries)", style=C_ERR)
            elif lp.get("pages_failed", 0) > 0:
                detail.append(f"\u2718 {lp['pages_failed']} pg failed", style=f"bold {C_ERR}")
            elif statuses.get("validation") == "done":
                detail.append("\u2714 complete", style=C_OK)

            if fs.get("validation") == "done":
                done_count += 1
            elif fs.get("extraction") == "failed":
                fail_count += 1

            tbl.add_row(
                vol_label(slug),
                row.get("page_count", "?"),
                *[badge(statuses[k]) for k, _ in STAGES],
                detail,
            )

        # Summary
        total = len(manifest)
        summ = Text()
        summ.append(f"\n  {done_count}/{total} complete", style="bold bright_white")
        if fail_count:
            summ.append(f"  \u2502  ", style="grey50")
            summ.append(f"{fail_count} failed", style=f"bold {C_ERR}")
        remaining = total - done_count - fail_count
        if remaining:
            summ.append(f"  \u2502  ", style="grey50")
            summ.append(f"{remaining} remaining", style=f"bold {C_WARN}")

        panels.append(Panel(
            Group(tbl, summ),
            title=f"[bold {C_BLUE}]\u2593\u2593 Pipeline \u2593\u2593[/]",
            border_style=C_BLUE, padding=(0, 1),
        ))

    # ── Live log tail ───────────────────────────────────────────────────
    if tail and not baseline_only:
        log_text = Text()
        for line in tail[-12:]:
            # Color code log lines
            if "ERROR" in line or "FAIL" in line or "failed" in line.lower():
                log_text.append(line + "\n", style=C_ERR)
            elif "WARNING" in line:
                log_text.append(line + "\n", style=C_ORANGE)
            elif "Completed" in line or "SUCCESS" in line:
                log_text.append(line + "\n", style=C_OK)
            elif "Starting" in line or "Processing" in line:
                log_text.append(line + "\n", style=C_TEAL)
            elif "Retrying" in line:
                log_text.append(line + "\n", style=C_WARN)
            else:
                log_text.append(line + "\n", style=C_DIM)

        panels.append(Panel(
            log_text,
            title=f"[bold {C_ORANGE}]\u2593\u2593 Live Log \u2593\u2593[/]",
            border_style=C_ORANGE, padding=(0, 1),
        ))

    # ── Errors (deduplicated) ───────────────────────────────────────────
    errs: Dict[str, List[str]] = defaultdict(list)
    for vol, lp in log_progress.items():
        e = lp.get("last_error")
        if e:
            errs[e].append(vol)

    if errs and not baseline_only:
        et = Text()
        for err, vols in errs.items():
            et.append("\n  \u26d4 ", style=f"bold {C_ERR}")
            et.append(err[:120], style=C_ERR)
            et.append("\n    \u2192 ", style="grey50")
            et.append(
                ", ".join(vols) if len(vols) <= 3 else f"ALL {len(vols)} volumes",
                style=C_ORANGE
            )
        et.append("\n")
        panels.append(Panel(et, title=f"[bold {C_ERR}]Blockers[/]", border_style=C_ERR))

    # ── Validation metrics ──────────────────────────────────────────────
    def metrics_panel(metrics: Dict, title: str, label: str = "") -> Panel:
        tbl = Table(
            box=box.SIMPLE_HEAVY, header_style="bold bright_white",
            border_style=C_ACCENT, expand=True, row_styles=["", "on grey7"],
        )
        tbl.add_column("Check", min_width=6)
        tbl.add_column("Description", min_width=26)
        tbl.add_column("Keys", justify="right", min_width=4, style=C_TEAL)
        tbl.add_column("Pass Rate", min_width=24)
        tbl.add_column("Accuracy", min_width=24)

        descs = {
            "W01": "Obj \u2192 Minor Tot",
            "W02": "Obj \u2192 Sub-Maj Tot",
            "W03": "Minor \u2192 Minor Tot",
            "W04": "Minor \u2192 Sub-Maj Tot",
            "W05": "Sub-Maj \u2192 Sub-Maj Tot",
            "A01": "Obj Minor Tot \u2192 Minor",
            "A02": "Obj Sub-Maj Tot \u2192 Sub-Maj",
            "A03": "Minor Sub-Maj Tot \u2192 Sub-Maj",
        }
        for ck in CHECK_ORDER:
            if ck not in metrics:
                continue
            m = metrics[ck]
            prob = ck in ("W02", "A02")
            ck_t = Text(f"\u26a0 {ck}" if prob else ck, style=f"bold {C_ERR}" if prob else f"bold {C_TEAL if ck[0] == 'W' else C_GOLD}")
            tbl.add_row(
                ck_t,
                Text(descs.get(ck, ""), style=f"bold {C_ORANGE}" if prob else ""),
                str(m["keys"]),
                bar(m["pass_pct"]),
                bar(m["acc_pct"]) if m["keys"] > 0 else Text("\u2500", style="grey30"),
            )
        wa = w_accuracy(metrics)
        foot = Text()
        foot.append(f"\n  HEALTH ", style="bold white")
        n = 25
        filled = int(wa / 100 * n)
        for i in range(n):
            c = ("bright_red" if i/n < 0.4 else "dark_orange" if i/n < 0.6 else "bright_yellow" if i/n < 0.8 else "bright_green")
            foot.append("\u2588" if i < filled else "\u2591", style=c if i < filled else "grey23")
        foot.append(f" {wa:.1f}%", style="bold bright_white")
        total_keys = sum(m["keys"] for m in metrics.values())
        foot.append(f"  ({total_keys:,} keys)", style="grey50")
        return Panel(Group(tbl, foot), title=f"[bold {C_ACCENT}]{title}[/] {label}", border_style=C_ACCENT, padding=(0, 1))

    # Baseline
    r0_csv = RUNS_DIR / "R0" / "validation_summary.csv"
    r0 = load_validation(r0_csv)

    if baseline_only:
        own = load_validation(run_dir / "validation_summary.csv")
        if own:
            panels.append(metrics_panel(own, f"Run {run_id}", "[dim]baseline[/]"))
    else:
        if r0:
            panels.append(metrics_panel(r0, "Baseline (R0)", "[dim]27-run[/]"))
        # Current run validation
        cur_csv = run_dir / "validation" / "validation_summary.csv"
        cur = load_validation(cur_csv)
        if cur:
            panels.append(metrics_panel(cur, f"Run {run_id}"))

    # ── Footer ──────────────────────────────────────────────────────────
    now = datetime.now().strftime("%H:%M:%S")
    ft = Text()
    ft.append(f"\n  \u23f0 {now}", style=f"bold {C_TEAL}")
    if is_alive:
        ft.append("  \u2502  ", style="grey30")
        ft.append("tracking live  ", style=f"bold {C_OK}")
        ft.append("Ctrl+C to detach", style=C_DIM)
    else:
        ft.append("  \u2502  ", style="grey30")
        ft.append("process ended", style=C_DIM)
    ft.append("  \u2502  Runs: ", style="grey30")
    for i, r in enumerate(list_runs()):
        ft.append(r, style=f"bold {C_ACCENT}" if r == run_id else "grey50")
        if i < len(list_runs()) - 1:
            ft.append(" ", style="grey30")
    ft.append("\n")
    panels.append(ft)

    return Group(*panels)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="OCR Pipeline Live Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  (default)         Auto-attach to running pipeline process, live-track it
  --run-id R1       Track a specific run (live if running, snapshot if not)
  --snapshot        One-shot snapshot instead of live tracking
  --list            List available runs and their status
  --interval N      Refresh interval in seconds (default: 3)
        """,
    )
    parser.add_argument("--run-id", default=None, help="Track specific run")
    parser.add_argument("--snapshot", action="store_true", help="One-shot snapshot")
    parser.add_argument("--list", action="store_true", help="List runs")
    parser.add_argument("--interval", type=int, default=3, help="Refresh interval (seconds)")
    args = parser.parse_args()

    # ── List mode ───────────────────────────────────────────────────────
    if args.list:
        console.print(Rule("Available Runs", style=C_ACCENT))
        procs = find_pipeline_processes()
        proc_map = {p["run_id"]: p for p in procs if p.get("run_id")}
        for r in list_runs():
            rd = RUNS_DIR / r
            p = proc_map.get(r)
            st = (
                Text(f" \u25b6 LIVE PID {p['pid']} ", style="bold white on green")
                if p else Text(" \u25cf stopped ", style="grey50")
            )
            vc = rd / "validation" / "validation_summary.csv"
            if not vc.exists():
                vc = rd / "validation_summary.csv"
            vt = Text("\u2714", style=C_OK) if vc.exists() else Text("\u00b7", style=C_DIM)
            console.print(f"  ", Text(r, style=f"bold {C_ACCENT}"), "  ", st, "  ", vt)
        if procs:
            console.print()
            for p in procs:
                if p.get("run_id") not in [r for r in list_runs()]:
                    console.print(f"  [bold {C_WARN}]Unlisted process:[/] PID {p['pid']}  {p['cmd'][:60]}")
        return 0

    # ── Resolve what to track ───────────────────────────────────────────
    proc: Optional[Dict[str, Any]] = None
    run_dir: Optional[Path] = None
    run_id: Optional[str] = None

    if args.run_id:
        run_id = args.run_id
        run_dir = RUNS_DIR / run_id
        # Check if this run has a live process
        procs = find_pipeline_processes()
        for p in procs:
            if p.get("run_id") == run_id:
                proc = p
                break
            rd = resolve_run_dir(p)
            if rd and rd == run_dir:
                proc = p
                break
    else:
        # Auto-detect: find any running pipeline process
        procs = find_pipeline_processes()
        if procs:
            proc = procs[0]
            run_dir = resolve_run_dir(proc)
            run_id = proc.get("run_id") or (run_dir.name if run_dir else "?")
            console.print(f"  [{C_TEAL}]Auto-attached to PID {proc['pid']}[/]  run={run_id}")
        else:
            # No running process — show latest run
            run_id = list_runs()[-1] if list_runs() else None
            if run_id:
                run_dir = RUNS_DIR / run_id
                console.print(f"  [{C_DIM}]No running process. Showing latest run: {run_id}[/]")
            else:
                console.print(f"  [{C_ERR}]No runs found and no pipeline process running.[/]")
                return 1

    if not run_dir or not run_dir.exists():
        console.print(f"  [{C_ERR}]Run directory not found: {run_dir}[/]")
        return 1

    # ── Snapshot mode ───────────────────────────────────────────────────
    if args.snapshot or (proc is None and not (proc and pid_alive(proc["pid"]))):
        console.print(build_dashboard(run_dir, run_id, proc, 0))
        return 0

    # ── Live tracking mode ──────────────────────────────────────────────
    tick = 0
    try:
        with Live(
            build_dashboard(run_dir, run_id, proc, tick),
            console=console,
            refresh_per_second=1,
            screen=True,
        ) as live:
            while True:
                time.sleep(args.interval)
                tick += 1

                # Re-scan process info (CPU/MEM update)
                if proc:
                    fresh = find_pipeline_processes()
                    found = False
                    for p in fresh:
                        if p["pid"] == proc["pid"]:
                            proc = p
                            found = True
                            break
                    if not found:
                        proc = None  # process exited

                live.update(build_dashboard(run_dir, run_id, proc, tick))

                # If process exited, show final state and wait a beat
                if proc is None or not pid_alive(proc.get("pid", -1)):
                    live.update(build_dashboard(run_dir, run_id, None, tick))
                    time.sleep(2)
                    break

    except KeyboardInterrupt:
        console.print(f"\n  [{C_DIM}]Detached from live tracker.[/]")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
