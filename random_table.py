import os
import json
import re
from typing import Any
from pypdf import PdfReader
from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel
from pypdf import PdfReader  # type: ignore

load_dotenv()
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 3500

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# --- PDF extraction ---
def extract_pdf_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join(
        page.extract_text() or "" for page in reader.pages
    )


# --- Claude call (NO SCHEMA) ---
def call_claude_dynamic(text: str) -> Any:
    prompt = f"""
Extract all structured information from this document.

Return ONLY valid JSON.

Requirements:
- No explanations or markdown
- Use arrays/objects appropriately
- Preserve table structure if present
- Use meaningful keys inferred from the data
- If tabular data exists, return as an array of objects (rows)

Document:
{text[:15000]}
"""

    response = client.messages.create(
        model=MODEL,
        temperature=0,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    return safe_json_parse(raw)


# --- Robust JSON parsing ---
def safe_json_parse(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # attempt recovery
        match = re.search(r"\{.*\}|\[.*\]", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError("Failed to parse JSON:\n" + raw)


# --- MAIN ---
if __name__ == "__main__":
    pdf_path = "A91 Partners II 2025-08-29_PCAP Q2 2025_Gautam Kumra-1.pdf"
    import time
    st = time.time()
    text = extract_pdf_text(pdf_path)
    result = call_claude_dynamic(text)
    end=time.time()

    print("time taken",end-st)

    print(json.dumps(result, indent=2))