"""Check that each extracted value is backed by its page in the report.

Input: a CSV with ticker, metric, year, value (as printed), unit_as_printed, page, quote.
Adds page_ok, quote_on_page, value_in_quote, unit_ok, value_tco2e and evidence_ok.
Both extractors run these checks before saving; the command re-checks a file in place.

Usage:
    python -m src.validate.evidence data/processed/rules_extractions.csv
"""

import argparse
import re
from functools import cache, lru_cache
from pathlib import Path

import pandas as pd
import pymupdf

from src.read.find_pages import RAW, SOURCES, TEST_SOURCES, read_sources
from src.read.text_utils import SPACES, normalize, unit_scale

WORD = re.compile(r"[a-z0-9]+")
CHECKS = ["page_ok", "quote_on_page", "value_in_quote", "unit_ok"]


@cache
def pdf_files() -> dict[str, str]:
    sources = read_sources([SOURCES, TEST_SOURCES])
    return dict(zip(sources["euronext_ticker"], sources["file_name"]))


@lru_cache(maxsize=512)
def page_text(ticker: str, page: int) -> str | None:
    with pymupdf.open(RAW / pdf_files()[ticker]) as doc:
        return doc[page - 1].get_text() if 1 <= page <= doc.page_count else None


def words(text: str) -> list[str]:
    # the subscript of "tCO2" is often stored apart from the word, or lost: compare "co2" as "co"
    return WORD.findall(normalize(text).replace("co2", "co "))


def quote_on_page(quote: str, text: str) -> bool:
    """Every word of the quote appears on the page. Word order is not checked,
    because text extraction often reorders table cells."""
    page_words = set(words(text))
    quote_words = words(quote)
    return bool(quote_words) and all(w in page_words for w in quote_words)


def value_pattern(value: float) -> re.Pattern:
    """Match a figure however it is printed: 1234567, 1,234,567, 1 234 567, 1.3 or 1,3."""
    if float(value).is_integer():
        digits = str(int(abs(value)))
        groups = [digits[max(0, i - 3):i] for i in range(len(digits), 0, -3)][::-1]
        body = f"[\\s,.{SPACES}]?".join(groups)
    else:
        whole, frac = str(abs(value)).split(".")
        body = whole + "[.,]" + frac
    return re.compile(r"(?<![\d.,])" + body + r"(?!\d)")


def value_in_quote(value: float, quote: str) -> bool:
    return bool(value_pattern(value).search(quote))


def check(records: pd.DataFrame) -> pd.DataFrame:
    results = []
    for r in records.itertuples():
        text = page_text(r.ticker, int(r.page)) if pd.notna(r.page) else None
        scale = unit_scale(str(r.unit_as_printed)) if pd.notna(r.unit_as_printed) else None
        results.append({
            "page_ok": text is not None,
            "quote_on_page": text is not None and quote_on_page(str(r.quote), text),
            "value_in_quote": value_in_quote(float(r.value), str(r.quote)),
            "unit_ok": scale is not None,
            "value_tco2e": round(float(r.value) * scale) if scale is not None else None,
        })
    results = pd.DataFrame(results)
    out = pd.concat([records.drop(columns=results.columns, errors="ignore").reset_index(drop=True), results], axis=1)
    out["evidence_ok"] = out[CHECKS].all(axis=1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()

    checked = check(pd.read_csv(args.csv))
    checked.to_csv(args.csv, index=False)
    print(f"{checked.evidence_ok.sum()}/{len(checked)} records pass every check, saved to {args.csv}")
    for col in CHECKS:
        print(f"  {col:15s} {checked[col].mean():.0%}")


if __name__ == "__main__":
    main()
