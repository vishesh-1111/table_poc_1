"""
clean.py
--------
Extracts clean tabular records from the pre-processed JSON file.

The input JSON is a list of table objects with this shape:
  [
    {
      "table_number": 1,
      "page_number": null,
      "rows": [
        ["Col1", "Col2", ...],   <- first row is the header
        ["val1", "val2", ...],   <- subsequent rows are data
        ...
      ]
    },
    ...
  ]

Output: JSON written to tabula-VR capital.clean.json
Schema:
  {
    "tables": [
      {
        "headers": ["Col1", "Col2", ...],
        "records": [
          {"Col1": "val", "Col2": "val", ...},
          ...
        ]
      },
      ...
    ]
  }
"""

import json
import re
import sys
from pathlib import Path


# ── Constants ────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_header_row(row):
    """A row is a header if its first non-empty cell doesn't look like a date."""
    for cell in row:
        val = str(cell).strip()
        if val:
            return not _DATE_RE.match(val)
    return False


def _normalise(text):
    """Collapse internal whitespace."""
    return " ".join(str(text).split())


# ── Main extraction logic ─────────────────────────────────────────────────────

def extract(tables_raw):
    """
    Process the list of table dicts and return:
      {"tables": [{"headers": [...], "records": [...]}, ...]}
    """
    result_tables = []

    for tbl in tables_raw:
        table_num = tbl.get("table_number", "?")
        rows = tbl.get("rows", [])

        if not rows:
            print(f"  WARNING: Table {table_num} has no rows. Skipping.", file=sys.stderr)
            continue

        # ── Determine headers ────────────────────────────────────────────────
        # Walk rows until we find the header row (first row not starting with a date)
        first_row = rows[0]
        if _is_header_row(first_row):
            headers = [_normalise(c) for c in first_row]
            data_rows = rows[1:]
        else:
            # No header row — this is a continuation table; we'll still process it
            # but flag it. Headers will be positional placeholders.
            print(
                f"  WARNING: Table {table_num} has no header row. "
                "Using positional column names.",
                file=sys.stderr,
            )
            n_cols = max(len(r) for r in rows)
            headers = [f"Col{i+1}" for i in range(n_cols)]
            data_rows = rows

        n_cols = len(headers)
        records = []

        for row_idx, row in enumerate(data_rows):
            # Skip blank rows
            if not any(str(c).strip() for c in row):
                continue

            # Skip repeated header rows that crept into the data
            if _is_header_row(row):
                print(
                    f"  INFO: Table {table_num}, row {row_idx}: repeated header skipped.",
                    file=sys.stderr,
                )
                continue

            values = [str(c).strip() for c in row]
            n_vals = len(values)

            if n_vals < n_cols:
                values += [""] * (n_cols - n_vals)          # pad short rows
            elif n_vals > n_cols:
                print(
                    f"  WARNING: Table {table_num}, row {row_idx}: "
                    f"{n_vals} values for {n_cols} headers. Merging extras into last column.",
                    file=sys.stderr,
                )
                overflow = " ".join(values[n_cols - 1:])
                values = values[: n_cols - 1] + [overflow]

            records.append(dict(zip(headers, values)))

        result_tables.append({"headers": headers, "records": records})

    return {"tables": result_tables}


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    input_path  = Path("tabula_raw_tables.json")
    output_path = Path("tabula-VR capital.clean.json")

    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading : {input_path}")
    with input_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    print(f"Tables  : {len(raw)}")
    result = extract(raw)

    print(f"\nTables extracted: {len(result['tables'])}")
    for i, tbl in enumerate(result["tables"]):
        print(f"  Table {i+1}: {len(tbl['headers'])} columns, {len(tbl['records'])} records")
        print(f"    Headers : {tbl['headers']}")
        if tbl["records"]:
            print(f"    Sample  : {json.dumps(tbl['records'][0], ensure_ascii=False)}")

    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    print(f"\nOutput  : {output_path}")


if __name__ == "__main__":
    main()