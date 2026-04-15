#!/usr/bin/env python3
"""Hybrid PDF table extraction using Tabula + Anthropic (Structured Output).

Flow:
1. Tabula extracts all tables as raw JSON.
2. Anthropic structures each table into normalized JSON records using Pydantic schema.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, List

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel
from pypdf import PdfReader  # type: ignore

load_dotenv()

# ----------------------------
# Pydantic Schema
# ----------------------------
class Transaction(BaseModel):
    date: str = ""
    transaction_description: str = ""
    amount_inr: str = ""
    balance_units: str = ""


class TableResponse(BaseModel):
    rows: List[Transaction]


# ----------------------------
# Runtime configuration
# ----------------------------
PDF_PATH = "PURVA Residential Excellence Fund - I.pdf"
TABULA_JAR_PATH = "external/tabula-1.0.5-jar-with-dependencies.jar"
PDF_PAGES = "1,2"
OUTPUT_JSON_PATH = "structured_tables.json"
TABULA_RAW_JSON_PATH = "tabula_raw_tables.json"
JAVA_BIN = "/usr/lib/jvm/java-8-openjdk-amd64/jre/bin/java"

# Use a valid structured-output capable model
ANTHROPIC_MODEL = "claude-sonnet-4-6"
MAX_TOKENS_PER_TABLE = 10000


STRUCTURE_PROMPT = """Extract rows from the table that match:

- Date
- Transaction Description
- Amount (INR)
- BalanceUnits

Rules:
- Match columns semantically (e.g., "Txn Date", "Description", etc.)
-  where ALL 4 fields are not  present use empty cell
- Ignore headers, totals, malformed rows
- Do NOT infer missing values
- If no valid rows exist, return empty rows
"""


# ----------------------------
# Utility Functions
# ----------------------------
def resolve_path(path_value: Path, project_root: Path) -> Path:
    if path_value.is_absolute() or path_value.exists():
        return path_value.resolve()
    return (project_root / path_value).resolve()


def get_pdf_page_count(pdf_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)


def validate_pages_spec(pages_spec: str, total_pages: int) -> str:
    pages_spec = pages_spec.strip()

    if pages_spec.lower() == "all":
        return "all"

    tokens = [t.strip() for t in pages_spec.split(",") if t.strip()]
    for token in tokens:
        if "-" in token:
            start, end = map(int, token.split("-"))
            if start < 1 or end > total_pages or start > end:
                raise ValueError("Invalid page range")
        else:
            page = int(token)
            if page < 1 or page > total_pages:
                raise ValueError("Invalid page number")

    return ",".join(tokens)


# ----------------------------
# Tabula Extraction
# ----------------------------
def run_tabula_json(
    pdf_path: Path,
    jar_path: Path,
    java_bin: str,
    pages_spec: str,
) -> list[dict[str, Any]]:
    cmd = [
        java_bin,
        "-jar",
        str(jar_path),
        "--format",
        "JSON",
        "--pages",
        pages_spec,
        "-t",
        "--stream",
        str(pdf_path),
    ]

    print(f"Running Tabula: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    
    print("result:", result.stdout)

    return json.loads(result.stdout or "[]")


def normalize_tabula_tables(tabula_tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []

    for idx, table in enumerate(tabula_tables, start=1):
        rows = [
            [str(cell.get("text", "")).strip() for cell in row]
            for row in table.get("data", [])
        ]

        if not rows:
            continue

        normalized.append(
            {
                "table_number": idx,
                "page_number": table.get("page"),
                "rows": rows[:50],  # limit size for stability
            }
        )

    return normalized


# ----------------------------
# Anthropic Structuring (FIXED)
# ----------------------------
def structure_table_with_anthropic(
    client: anthropic.Anthropic,
    table_payload: dict[str, Any],
) -> dict[str, Any]:
    prompt = (
        f"{STRUCTURE_PROMPT}\n\n"
        f"Input table JSON:\n{json.dumps(table_payload, ensure_ascii=False)}"
    )

    try:
        response = client.messages.parse(
            model=ANTHROPIC_MODEL,
            max_tokens=MAX_TOKENS_PER_TABLE,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            output_format=TableResponse,
        )

        parsed: TableResponse = response.parsed_output

        return {
            "table_number": table_payload["table_number"],
            "page_number": table_payload["page_number"],
            "rows": [r.model_dump() for r in parsed.rows],
        }

    except Exception as e:
        print("Structured parsing failed:", e)
        return {
            "table_number": table_payload["table_number"],
            "page_number": table_payload["page_number"],
            "rows": [],
        }


def structure_tables_with_anthropic(
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    client = anthropic.Anthropic()
    results = []

    for i, table in enumerate(tables, 1):
        print(f"Processing table {i}/{len(tables)}")
        structured = structure_table_with_anthropic(client, table)
        results.append(structured)

    return results


# ----------------------------
# Output
# ----------------------------
def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ----------------------------
# Main
# ----------------------------
def main():
    root = Path(__file__).resolve().parent

    pdf_path = resolve_path(Path(PDF_PATH), root)
    jar_path = resolve_path(Path(TABULA_JAR_PATH), root)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Missing ANTHROPIC_API_KEY")
        sys.exit(1)

    total_pages = get_pdf_page_count(pdf_path)
    pages = validate_pages_spec(PDF_PAGES, total_pages)

    tabula_tables = run_tabula_json(pdf_path, jar_path, JAVA_BIN, pages)
    normalized = normalize_tabula_tables(tabula_tables)

    write_json(Path(TABULA_RAW_JSON_PATH), normalized)

    if not normalized:
        write_json(Path(OUTPUT_JSON_PATH), [])
        return

    structured = structure_tables_with_anthropic(normalized)
    write_json(Path(OUTPUT_JSON_PATH), structured)

    print("Done.")


if __name__ == "__main__":
    main()