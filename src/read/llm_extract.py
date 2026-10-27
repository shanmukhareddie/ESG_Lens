"""Extract GHG figures with an LLM (Groq), from the pages chosen by the page finder.

Every reply is cached in data/llm_cache/, so re-running never pays for the same call twice.

Usage:
    python -m src.read.llm_extract                 # the 12 gold-set companies
    python -m src.read.llm_extract --tickers BN    # one company
    python -m src.read.llm_extract --all           # every report
"""

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

import groq
import pandas as pd
import pymupdf
from dotenv import load_dotenv
from pydantic import ValidationError

from src.read.find_pages import RAW, SOURCES, rank_pages
from src.read.schema import EmissionRecord
from src.read.text_utils import layout_text, load_taxonomy

MODEL = "openai/gpt-oss-120b"
PAGES_PER_REPORT = 4
PROMPT_BUDGET = 11000   # characters of page text, about 4,000 tokens: the free tier allows 8,000 per minute
CACHE = Path("data/llm_cache")
OUT = Path("data/processed/llm_extractions.csv")
GOLD = Path("data/gold/gold_labels.csv")
PAUSE = 2.0

SYSTEM_PROMPT = """Act as a Data Scientist and extract greenhouse gas emissions from the sustainability statement of a company's annual report.

Pages are given line by line, with " | " between table columns. Read the column headers
(years such as 2025, 2024, base year) to know which figure belongs to which year.

Return only a JSON object: {"records": [...]}. Each record has exactly these fields:
  metric           one of the metric names listed by the user
  year             2025 or 2024 (ignore other years, base years and targets)
  value            the figure exactly as printed, written as a plain number: "1,234,567" -> 1234567,
                   "698 274" -> 698274, "1.3" -> 1.3. Do not convert units.
  unit_as_printed  the unit printed for that figure, e.g. "tCO2eq", "ktCO2eq", "Mt CO2 eq."
                   (it is often in the row label, the column header or the table title)
  page             the number in the "=== PAGE n ===" marker of the page you read it from
  quote            the table row copied word for word from the page: the label and its figures

Rules:
- Use the group / consolidated figure, not a segment, region or subsidiary column.
- Scope 3 is the total of all categories, never a single category.
- Totals are Scope 1 + Scope 2 + Scope 3; Scope 1+2 subtotals are not totals.
- If a page holds several tables, use the one that lists Scope 1, 2 and 3 and the totals together.
- If a figure is not on the pages, leave it out. Never guess or calculate a value."""


def metric_guide() -> str:
    lines = []
    for name, d in load_taxonomy().items():
        lines.append(f"- {name}: {d['description']}. Printed as e.g. "
                     + "; ".join(f'"{x}"' for x in d["labels_seen"][:3])
                     + ". Not: " + "; ".join(f'"{x}"' for x in d["not_this"][:2]))
    return "\n".join(lines)


KEEP_LINE = re.compile(r"\d|scope|ghg|ges|emission|total|location|market|co2|tonne|ton\b", re.IGNORECASE)


def compact(text: str) -> str:
    """Keep table lines (figures, labels, units, year headers) and drop long prose."""
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln and KEEP_LINE.search(ln) and len(ln) < 160)


def build_prompt(company: str, pages: list[tuple[int, str]]) -> str:
    parts, used = [], 0
    for page, text in pages:          # best page first, until the budget is spent
        block = f"=== PAGE {page} ===\n{compact(text)}"
        if parts and used + len(block) > PROMPT_BUDGET:
            break
        parts.append(block[:PROMPT_BUDGET])
        used += len(block)
    return f"Company: {company}\n\nMetrics:\n{metric_guide()}\n\nPages:\n" + "\n\n".join(parts)


def ask(client: groq.Groq, messages: list[dict]) -> str:
    for _ in range(4):
        try:
            reply = client.chat.completions.create(
                model=MODEL, messages=messages, temperature=0, reasoning_effort="low",
                max_completion_tokens=3000, response_format={"type": "json_object"},
            )
            return reply.choices[0].message.content
        except groq.RateLimitError:
            time.sleep(65)    # the token budget refills every minute
        except groq.APIConnectionError:
            time.sleep(15)    # network hiccup
    raise RuntimeError("Groq request failed 4 times (rate limit or network)")


def parse(ticker: str, raw: str) -> tuple[list[EmissionRecord], list[str]]:
    try:
        items = json.loads(raw).get("records", [])
    except json.JSONDecodeError as e:
        return [], [f"invalid JSON: {e}"]
    records, errors = [], []
    for item in items:
        try:
            records.append(EmissionRecord(ticker=ticker, **item))
        except (ValidationError, TypeError) as e:
            errors.append(f"{item}: {e}")
    return records, errors


def report_pages(file_name: str) -> list[tuple[int, str]]:
    """Best pages of a report as layout-preserving text."""
    path = RAW / file_name
    with pymupdf.open(path) as doc:
        return [(p, layout_text(doc[p - 1])) for p, _ in rank_pages(path, PAGES_PER_REPORT)]


def extract(client: groq.Groq, ticker: str, company: str, file_name: str) -> list[EmissionRecord]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(company, report_pages(file_name))}]
    # the cache is keyed on the exact request, so a new prompt or model is never served an old answer
    key = hashlib.sha256(json.dumps([MODEL, messages]).encode()).hexdigest()[:16]
    cache_file = CACHE / f"{ticker}.json"
    if cache_file.exists():
        cached = json.loads(cache_file.read_text())
        if cached.get("key") == key:
            return parse(ticker, cached["response"])[0]

    raw = ask(client, messages)
    records, errors = parse(ticker, raw)
    if errors:   # one retry, telling the model what was wrong
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Some records were invalid:\n" + "\n".join(errors[:10])
                      + "\nReturn the full corrected JSON object."}]
        raw = ask(client, messages)
        records, errors = parse(ticker, raw)
        if errors:
            print(f"  {ticker}: {len(errors)} records still invalid and dropped")

    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"key": key, "model": MODEL, "response": raw}, indent=1))
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    client = groq.Groq()
    sources = pd.read_csv(SOURCES)
    if args.tickers:
        sources = sources[sources["euronext_ticker"].isin(args.tickers)]
    elif not args.all:
        sources = sources[sources["euronext_ticker"].isin(pd.read_csv(GOLD)["ticker"].unique())]

    rows = []
    for r in sources.itertuples():
        if not (RAW / r.file_name).exists():
            continue
        records = extract(client, r.euronext_ticker, r.company_full_name, r.file_name)
        rows += [rec.model_dump() for rec in records]
        print(f"{r.euronext_ticker:6s} {len(records)} records", flush=True)
        time.sleep(PAUSE)

    df = pd.DataFrame(rows).drop_duplicates(["ticker", "metric", "year"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"saved {len(df)} values for {df['ticker'].nunique()} companies to {OUT}")


if __name__ == "__main__":
    main()
