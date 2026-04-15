## Hybrid Table Extraction (Tabula + Anthropic)

This project now supports a hybrid pipeline:

1. Tabula extracts raw tables from the PDF as JSON.
2. Anthropic converts each extracted table into structured JSON records.

### Prerequisites

- Java installed and accessible
- Tabula JAR at `external/tabula-1.0.5-jar-with-dependencies.jar`
- Anthropic API key

### Install dependencies

```bash
uv sync
```

### Configure API key

```bash
export ANTHROPIC_API_KEY="your_api_key_here"
```

### Run

```bash
python3 poc.py
```

### Configure in code

CLI arguments were removed. Edit the runtime configuration block in `poc.py`:

- `PDF_PATH`
- `TABULA_JAR_PATH`
- `PDF_PAGES` (examples: `all`, `1,3-5`)
- `OUTPUT_JSON_PATH`
- `TABULA_RAW_JSON_PATH`
- `JAVA_BIN`
- `ANTHROPIC_MODEL`
- `MAX_TOKENS_PER_TABLE`

If `PDF_PAGES` contains page numbers beyond the actual PDF page count, the script raises an error.

### Outputs

- `tabula_raw_tables.json`: normalized raw table data from Tabula
- `structured_tables.json`: final structured table records returned by Anthropic
# table_poc_1
