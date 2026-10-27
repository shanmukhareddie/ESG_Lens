"""Find the pages of a report that most likely hold the GHG emissions table.

Usage:
    python -m src.read.find_pages          # writes data/processed/candidate_pages.csv
    top_pages("BN")                        # [(page, text), ...] for one company
"""

import argparse
import re
from pathlib import Path

import pandas as pd
import pymupdf

from src.read.text_utils import normalize, unit_scale

SOURCES = Path("data/cac40_fy2025_sources.csv")
RAW = Path("data/raw")
OUT = Path("data/processed/candidate_pages.csv")
TOP_N = 5

# A page only has to mention a metric to count, so these are looser than the taxonomy rules.
MENTIONS = [
    r"scope\s?1\b",
    r"scope\s?2.{0,40}location|location.{0,40}scope\s?2",
    r"scope\s?2.{0,40}market|market.{0,40}scope\s?2",
    r"scope\s?3|indirect",
    r"total.{0,40}location|location.{0,40}total",
    r"total.{0,40}market|market.{0,40}total",
]
BIG_NUMBER = re.compile(r"\b\d{1,3}(?:[ ,.\u202f]\d{3})+\b")


def score_page(text: str) -> int:
    t = normalize(text)
    score = 3 if re.search(r"\be1-6\b", t) else 0
    score += sum(bool(re.search(p, t)) for p in MENTIONS)
    if "location" in t and re.search(r"market|marche", t):
        score += 1
    if unit_scale(t) is not None:
        score += 1
    if len(BIG_NUMBER.findall(text)) >= 15:   # a table rather than prose
        score += 1
    return score


def rank_pages(pdf_path: Path, n: int = TOP_N) -> list[tuple[int, int]]:
    """Return (page, score) for the n best pages, best first. Pages are 1-based."""
    with pymupdf.open(pdf_path) as doc:
        scores = [(score_page(page.get_text()), i + 1) for i, page in enumerate(doc)]
    best = sorted(scores, key=lambda s: (-s[0], s[1]))[:n]
    return [(page, score) for score, page in best if score > 0]


def top_pages(ticker: str, n: int = TOP_N) -> list[tuple[int, str]]:
    path = RAW / f"{ticker}_FY2025.pdf"
    with pymupdf.open(path) as doc:
        return [(p, doc[p - 1].get_text()) for p, _ in rank_pages(path, n)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=TOP_N)
    args = parser.parse_args()

    rows = []
    for r in pd.read_csv(SOURCES).itertuples():
        path = RAW / r.file_name
        if not path.exists():
            print(f"skipping {r.euronext_ticker}: {path} not found")
            continue
        for rank, (page, score) in enumerate(rank_pages(path, args.top), 1):
            rows.append({"ticker": r.euronext_ticker, "rank": rank, "page": page, "score": score})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"saved {len(rows)} candidate pages to {OUT}")


if __name__ == "__main__":
    main()
