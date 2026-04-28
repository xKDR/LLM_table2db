#!/usr/bin/env python3
"""Run the local snippet baseline extraction loop.

This wrapper uses the existing extraction workflow functions but intentionally
skips the legacy 5-schema validation step. It is meant for the local
OCR self-correction workspace only.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_workflow():
    root = repo_root()
    workflow_dir = root / "LOCAL/ocr_self_correction/pipeline"
    sys.path.insert(0, str(workflow_dir))

    from extract_workflow import (  # type: ignore
        extract_data_with_gemini,
        extract_pdf_to_images,
        run_csv_cleaner,
        run_csv_combiner,
        setup_logging,
    )
    from schemas import get_schemas  # type: ignore

    return {
        "extract_pdf_to_images": extract_pdf_to_images,
        "extract_data_with_gemini": extract_data_with_gemini,
        "run_csv_cleaner": run_csv_cleaner,
        "run_csv_combiner": run_csv_combiner,
        "setup_logging": setup_logging,
        "get_schemas": get_schemas,
    }


def build_config(
    root: Path,
    row: dict[str, str],
    prompt_path: str,
    out_root: str,
    model: str,
    financial_years: list[str],
    workflow: dict[str, object],
    use_vertex: bool = False,
    vertex_project: str = "",
    vertex_location: str = "us-west1",
) -> dict[str, object]:
    volume_slug = f"{row['year']}_{row['volume']}"
    output_base = root / out_root / volume_slug
    csv_dir = output_base / "csv_outputs"

    config: dict[str, object] = {
        "PROJECT_ROOT": root,
        "PDF_PATH": root / row["snippet_pdf"],
        "OUTPUT_BASE": output_base,
        "PROMPT_FILE": root / prompt_path,
        "START_PAGE": int(row["extract_start_page"]),
        "END_PAGE": int(row["extract_end_page"]),
        "GEMINI_MODEL": model,
        "FINANCIAL_YEARS": financial_years,
        "SCHEMAS": workflow["get_schemas"](financial_years),
        "USE_VERTEX": use_vertex,
        "VERTEX_PROJECT": vertex_project,
        "VERTEX_LOCATION": vertex_location,
        "IMAGES_DIR": output_base / "images",
        "JSON_DIR": output_base / "json_outputs",
        "CSV_DIR": csv_dir,
        "CSV_DIR_SUB_MAJOR_HEAD": csv_dir / "sub_major_head_summary_csv",
        "CSV_DIR_MINOR_HEAD": csv_dir / "minor_head_summary_csv",
        "CSV_DIR_SUB_HEAD": csv_dir / "sub_head_summary_csv",
        "CSV_DIR_DETAILED": csv_dir / "detailed_head_summary_csv",
        "CSV_DIR_OBJECT_HEAD": csv_dir / "object_head_summary_csv",
    }
    return config


def write_metadata(
    config: dict[str, object],
    row: dict[str, str],
    prompt_path: str,
    model: str,
    run_id: str | None = None,
    validation_output: str | None = None,
    previous_run: str | None = None,
    timestamp: str | None = None,
) -> None:
    output_base = Path(config["OUTPUT_BASE"])
    payload = {
        "year": row["year"],
        "volume": row["volume"],
        "snippet_pdf": row["snippet_pdf"],
        "extract_start_page": row["extract_start_page"],
        "extract_end_page": row["extract_end_page"],
        "source_page_start": row["source_page_start"],
        "source_page_end": row["source_page_end"],
        "baseline_hotspot": row["baseline_hotspot"],
        "prompt_path": prompt_path,
        "model": model,
    }
    if run_id is not None:
        payload["run_id"] = run_id
    if validation_output is not None:
        payload["validation_output"] = validation_output
    if previous_run is not None:
        payload["previous_run"] = previous_run
    if timestamp is not None:
        payload["timestamp"] = timestamp
    output_base.mkdir(parents=True, exist_ok=True)
    (output_base / "run_metadata.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def read_manifest(root: Path, manifest_path: str) -> list[dict[str, str]]:
    path = root / manifest_path
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)



def process_snippet(
    root: Path,
    row: dict[str, str],
    prompt_path: str,
    out_root: str,
    model: str,
    financial_years: list[str],
    workflow: dict[str, object],
    run_id: str | None,
    validation_output: str | None,
    previous_run: str | None,
    run_timestamp: str,
    use_vertex: bool = False,
    vertex_project: str = "",
    vertex_location: str = "us-central1",
) -> str:
    """Process a single snippet end-to-end. Returns a status string."""
    slug = f"{row['year']}_{row['volume']}"
    try:
        config = build_config(
            root=root,
            row=row,
            prompt_path=prompt_path,
            out_root=out_root,
            model=model,
            financial_years=financial_years,
            workflow=workflow,
            use_vertex=use_vertex,
            vertex_project=vertex_project,
            vertex_location=vertex_location,
        )
        print(f"[{slug}] Starting extraction")
        write_metadata(
            config,
            row,
            prompt_path,
            model,
            run_id=run_id,
            validation_output=validation_output,
            previous_run=previous_run,
            timestamp=run_timestamp,
        )
        workflow["setup_logging"](config["OUTPUT_BASE"])
        workflow["extract_pdf_to_images"](config)
        workflow["extract_data_with_gemini"](config)
        workflow["run_csv_cleaner"](config)
        workflow["run_csv_combiner"](config)
        print(f"[{slug}] ✅ Done")
        return f"{slug}: OK"
    except Exception as e:
        print(f"[{slug}] ❌ FAILED: {e}")
        traceback.print_exc()
        return f"{slug}: FAILED ({e})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local snippet baseline extraction")
    parser.add_argument(
        "--manifest",
        default="LOCAL/ocr_self_correction/manifests/snippet_manifest.csv",
        help="Manifest CSV relative to repo root",
    )
    parser.add_argument(
        "--prompt-path",
        default="LOCAL/ocr_self_correction/prompts/base_prompt.md",
        help="Prompt file relative to repo root",
    )
    parser.add_argument(
        "--out-root",
        default="LOCAL/ocr_self_correction/outputs/runs/baseline_gemini3_flash_preview",
        help="Output root relative to repo root",
    )
    parser.add_argument(
        "--model",
        default="gemini-3-flash-preview",
        help="Gemini model name to pass through",
    )
    parser.add_argument(
        "--financial-years",
        default="Accounts_2018_19,Budget_2019_20,Revised_2019_20,Budget_2020_21",
        help="Comma-separated financial columns",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Explicit run identifier (e.g. R1, R2). Written into metadata.",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip the validation step after extraction",
    )
    parser.add_argument(
        "--previous-run",
        default=None,
        help="Path to previous run's validation summary CSV (for metadata only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned runs without executing Gemini extraction",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Max parallel snippet workers (0 = all snippets in parallel, 1 = sequential)",
    )
    parser.add_argument(
        "--use_vertex",
        action="store_true",
        default=False,
        help="Use Vertex AI (ADC) instead of Gemini API key",
    )
    parser.add_argument(
        "--project",
        default=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        help="Google Cloud project ID for Vertex AI (default: $GOOGLE_CLOUD_PROJECT)",
    )
    parser.add_argument(
        "--location",
        default=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        help="Google Cloud location for Vertex AI (default: us-central1)",
    )
    args = parser.parse_args()

    root = repo_root()

    # Load .env from LOCAL/ocr_self_correction/.env if present
    env_path = root / "LOCAL" / "ocr_self_correction" / ".env"
    if env_path.exists():
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(env_path)

    financial_years = [x.strip() for x in args.financial_years.split(",")]
    rows = read_manifest(root, args.manifest)

    run_timestamp = datetime.now(timezone.utc).isoformat()
    out_root_abs = root / args.out_root
    validation_output = str(out_root_abs / "validation")

    if args.dry_run:
        for row in rows:
            print(
                f"DRY RUN {row['year']}_{row['volume']}: "
                f"{row['snippet_pdf']} pages {row['extract_start_page']}-{row['extract_end_page']} "
                f"model={args.model}"
            )
        if not args.skip_validation:
            print(f"DRY RUN validation: input-base={out_root_abs} output-base={validation_output}")
        if args.run_id:
            print(f"DRY RUN run_id={args.run_id}")
        return 0

    if not args.use_vertex and not os.getenv("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY is not set in the environment.")
        print("Set it in the shell or .env, or use --use_vertex for Vertex AI auth.")
        return 2

    workflow = load_workflow()

    max_workers = args.workers if args.workers > 0 else len(rows)
    print(f"Processing {len(rows)} snippets with {max_workers} parallel workers")
    print("=" * 80)

    val_out = validation_output if not args.skip_validation else None

    if args.use_vertex:
        print(f"Backend: Vertex AI (project: {args.project}, location: {args.location})")
    else:
        print(f"Backend: Gemini API (GEMINI_API_KEY)")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                process_snippet,
                root=root,
                row=row,
                prompt_path=args.prompt_path,
                out_root=args.out_root,
                model=args.model,
                financial_years=financial_years,
                workflow=workflow,
                run_id=args.run_id,
                validation_output=val_out,
                previous_run=args.previous_run,
                run_timestamp=run_timestamp,
                use_vertex=args.use_vertex,
                vertex_project=args.project,
                vertex_location=args.location,
            ): row
            for row in rows
        }
        results = []
        for future in as_completed(futures):
            results.append(future.result())

    print("=" * 80)
    print("Extraction summary:")
    for r in results:
        print(f"  {r}")
    print("=" * 80)

    # --- Validation step ---
    if not args.skip_validation:
        print("=" * 80)
        print("RUNNING VALIDATION")
        print("=" * 80)
        validation_script = Path(__file__).resolve().parent / "run_validation.py"
        cmd = [
            sys.executable,
            str(validation_script),
            "--input-base", str(out_root_abs),
            "--output-base", validation_output,
        ]
        print(f"  cmd: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(root))
        if result.returncode != 0:
            print(f"WARNING: Validation exited with code {result.returncode}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
