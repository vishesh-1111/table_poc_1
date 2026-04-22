#!/usr/bin/env python3
"""
extract.py
----------
PDF table extraction pipeline: PDF -> Tabula -> Clean -> JSON

Flow:
  1. Tabula extracts raw tables from the PDF as JSON.
  2. Raw tables are normalised (ghost cells stripped, headers detected).
  3. Clean structured records are written to OUTPUT_JSON_PATH.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from pypdf import PdfReader  # type: ignore


# ── Configuration ─────────────────────────────────────────────────────────────

PDF_PATH          = "VR capital.pdf"
TABULA_JAR_PATH   = "external/tabula-1.0.5-jar-with-dependencies.jar"
JAVA_BIN          = "/usr/lib/jvm/java-8-openjdk-amd64/jre/bin/java"
PDF_PAGES         = "all"          # "all" or e.g. "1,3,5-8"

OUTPUT_JSON_PATH  = "structured_tables.json"   # final clean output
TABULA_RAW_PATH   = "tabula_raw_tables.json"   # intermediate (optional, kept for debugging)

MAX_ROWS_PER_TABLE = 50            # safety cap passed to tabula normaliser


# ── Constants ─────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── Path helpers ──────────────────────────────────────────────────────────────

def resolve(path_str: str, root: Path) -> Path:
    p = Path(path_str)
    if p.is_absolute() or p.exists():
        return p.resolve()
    return (root / p).resolve()


# ── PDF helpers ───────────────────────────────────────────────────────────────

def get_page_count(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def validate_pages(spec: str, total: int) -> str:
    spec = spec.strip()
    if spec.lower() == "all":
        return "all"
    for token in spec.split(","):
        token = token.strip()
        if "-" in token:
            s, e = map(int, token.split("-"))
            if s < 1 or e > total or s > e:
                raise ValueError(f"Invalid page range: {token}")
        else:
            p = int(token)
            if p < 1 or p > total:
                raise ValueError(f"Invalid page number: {token}")
    return spec


# ── Step 1 – Tabula extraction ────────────────────────────────────────────────

def run_tabula(pdf_path: Path, jar_path: Path, java_bin: str, pages: str) -> list[dict[str, Any]]:
    cmd = [
        java_bin,
        "-jar", str(jar_path),
        "--format", "JSON",
        "--guess",
        "--pages", pages,
        "--stream",
        str(pdf_path),
    ]
    print(f"[tabula] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Tabula failed:\n{result.stderr}")
    return json.loads(result.stdout or "[]")


def normalise_tabula(tabula_tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert raw Tabula cell-object rows into plain string rows."""
    normalised = []
    for idx, table in enumerate(tabula_tables, start=1):
        rows = [
            [str(cell.get("text", "")).strip() for cell in row]
            for row in table.get("data", [])
        ]
        if not rows:
            continue
        normalised.append({
            "table_number": idx,
            "page_number": table.get("page"),
            "rows": rows[:MAX_ROWS_PER_TABLE],
        })
    return normalised


# ── Step 2 – Cleaning ─────────────────────────────────────────────────────────

def _is_header_row(row: list[str]) -> bool:
    """Header rows have a non-date value in their first non-empty cell."""
    for cell in row:
        val = cell.strip()
        if val:
            return not _DATE_RE.match(val)
    return False


def _normalise_text(text: str) -> str:
    return " ".join(text.split())


def _parse_rows(rows: list[list[str]], headers: list[str], table_num: Any) -> list[dict[str, Any]]:
    """Map a list of plain string rows onto the given headers, returning records."""
    n_cols  = len(headers)
    records = []

    for row_idx, row in enumerate(rows):
        if not any(c.strip() for c in row):
            continue  # skip blank rows

        if _is_header_row(row):
            print(
                f"  INFO: Table {table_num}, row {row_idx}: repeated header skipped.",
                file=sys.stderr,
            )
            continue

        values = [c.strip() for c in row]
        n_vals = len(values)

        if n_vals < n_cols:
            values += [""] * (n_cols - n_vals)
        elif n_vals > n_cols:
            print(
                f"  WARNING: Table {table_num}, row {row_idx}: "
                f"{n_vals} values for {n_cols} headers — merging extras into last column.",
                file=sys.stderr,
            )
            overflow = " ".join(values[n_cols - 1:])
            values   = values[: n_cols - 1] + [overflow]

        records.append(dict(zip(headers, values)))

    return records


def clean(tables_raw: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Turn plain-string-row tables into labelled records.

    Continuation pages (no header row) inherit the headers from the previous
    table and their records are appended to it rather than creating a new entry.

    Returns:
      {
        "tables": [
          {"headers": [...], "records": [{col: val, ...}, ...]},
          ...
        ]
      }
    """
    result_tables: list[dict[str, Any]] = []
    last_headers: list[str] = []   # propagated across headerless continuations

    for tbl in tables_raw:
        table_num = tbl.get("table_number", "?")
        rows = tbl.get("rows", [])

        if not rows:
            print(f"  WARNING: Table {table_num} is empty. Skipping.", file=sys.stderr)
            continue

        if _is_header_row(rows[0]):
            # ── New logical table with its own header ─────────────────────────
            headers      = [_normalise_text(c) for c in rows[0]]
            last_headers = headers
            data_rows    = rows[1:]
            records      = _parse_rows(data_rows, headers, table_num)
            result_tables.append({"headers": headers, "records": records})

        else:
            # ── Continuation page — no header row ─────────────────────────────
            if last_headers:
                print(
                    f"  INFO: Table {table_num} has no header — "
                    "appending to previous table using its headers.",
                    file=sys.stderr,
                )
                records = _parse_rows(rows, last_headers, table_num)
                # Append into the most recent logical table
                result_tables[-1]["records"].extend(records)
            else:
                print(
                    f"  WARNING: Table {table_num} has no header and no prior table. Skipping.",
                    file=sys.stderr,
                )

    return {"tables": result_tables}


# ── Output ────────────────────────────────────────────────────────────────────

def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(f"[output] Written: {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    root = Path(__file__).resolve().parent

    pdf_path = resolve(PDF_PATH, root)
    jar_path = resolve(TABULA_JAR_PATH, root)

    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)
    if not jar_path.exists():
        print(f"ERROR: Tabula JAR not found: {jar_path}", file=sys.stderr)
        sys.exit(1)

    # ── 1. Extract with Tabula ────────────────────────────────────────────────
    total_pages  = get_page_count(pdf_path)
    pages_spec   = validate_pages(PDF_PAGES, total_pages)
    print(f"[pdf]    {pdf_path.name}  ({total_pages} pages, extracting: {pages_spec})")

    tabula_raw   = run_tabula(pdf_path, jar_path, JAVA_BIN, pages_spec)
    normalised   = normalise_tabula(tabula_raw)
    print(f"[tabula] {len(normalised)} table(s) extracted")

    # Save intermediate for debugging
    write_json(Path(TABULA_RAW_PATH), normalised)

    if not normalised:
        print("[clean]  No tables found. Writing empty output.")
        write_json(Path(OUTPUT_JSON_PATH), {"tables": []})
        return

    # ── 2. Clean ──────────────────────────────────────────────────────────────
    result = clean(normalised)
    print(f"\n[clean]  {len(result['tables'])} table(s) cleaned")
    for i, tbl in enumerate(result["tables"]):
        print(f"  Table {i+1}: {len(tbl['headers'])} cols, {len(tbl['records'])} records")
        print(f"    Headers : {tbl['headers']}")
        if tbl["records"]:
            print(f"    Sample  : {json.dumps(tbl['records'][0], ensure_ascii=False)}")

    # ── 3. Save ───────────────────────────────────────────────────────────────
    write_json(Path(OUTPUT_JSON_PATH), result)
    print("\nDone.")


if __name__ == "__main__":
    main()