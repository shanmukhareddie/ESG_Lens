"""Rule-based extraction of GHG figures, used as a baseline for the LLM extractor.

PDF tables have no structure, so rows are rebuilt from word positions. A line with
figures is a table row, its label is the text left of the first figure, and each
figure gets the year of the header column above it.

Usage:
    python -m src.read.rules_extract       # writes data/processed/rules_extractions.csv
"""

import re
import statistics
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pymupdf

from src.read.find_pages import RAW, SOURCES, rank_pages
from src.read.text_utils import dominant_unit_scale, label_matches, load_taxonomy, parse_number, unit_scale

OUT = Path("data/processed/rules_extractions.csv")
YEARS = (2024, 2025)
TAXONOMY = load_taxonomy()

YEAR = re.compile(r"^\(?(?:FY\s?|\d{1,2}/\d{1,2}/)?(20[1-3]\d)\)?(?:\s?\(\w\))?\*?$", re.I)
UNIT_TEXT = re.compile(
    r"(?i)(1,000 x tons? of co\s?2\s?e|thousands? of (metric )?(tonnes|tons)( of co2e?)?|milliers de tonnes"
    r"|million (tons|tonnes) of co2-?eq|mt co2 ?eq\.?|kt ?co2 ?eq|ktco2e?|t ?eq ?co2|tco2 ?e?q?|tco2-eq|tonnes co2e?)"
)


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def middle(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


def read_lines(page) -> list[list[Word]]:
    """Group the words of a page into visual lines, left to right."""
    words = [Word(*w[:5]) for w in page.get_text("words") if w[4].strip()]
    if not words:
        return []
    tolerance = 0.45 * statistics.median(w.y1 - w.y0 for w in words)
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.yc, w.x0)):
        if lines and abs(w.yc - statistics.fmean(x.yc for x in lines[-1])) <= tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def is_part_of_label(prev: Word | None, w: Word) -> bool:
    # the "1" in "Scope 1", the "2" in "Scopes 1, 2 & 3" or in "tCO 2 e"
    if prev is None or not re.fullmatch(r"\d{1,2}[,)]?", w.text):
        return False
    return bool(re.search(r"(?i)(scopes?|cat\.?|co|&|and|et|\d,)$", prev.text)) and w.x0 - prev.x1 < 25


def figures(line: list[Word], decimal: str) -> list[tuple[Word, float]]:
    merged: list[Word] = []
    for w in line:
        # French reports split "1 234 567" into several words
        prev = merged[-1] if merged else None
        if prev and re.fullmatch(r"\d{1,3}", prev.text) and re.fullmatch(r"\d{3}([.,]\d+)?", w.text) and w.x0 - prev.x1 < 4:
            merged[-1] = Word(prev.x0, prev.y0, w.x1, w.y1, f"{prev.text} {w.text}")
        else:
            merged.append(w)

    found, prev = [], None
    for w in merged:
        if not is_part_of_label(prev, w) and not YEAR.match(w.text):
            value = parse_number(w.text, decimal)
            if value is not None:
                found.append((w, value))
        prev = w
    return found


def year_columns(line: list[Word]) -> list[tuple[int, Word]]:
    columns = []
    for w in line:
        m = YEAR.match(re.sub(r"[   ]", " ", w.text))
        if m:
            columns.append((int(m.group(1)), w))
    return columns


def column_year(cell: Word, header: list[tuple[int, Word]]) -> int | None:
    year, col = min(header, key=lambda h: abs(h[1].middle - cell.middle))
    return year if abs(col.middle - cell.middle) < 35 else None


def find_unit(texts: list[str], page_unit: float | None) -> tuple[float, str]:
    """Scale to tCO2e and the unit as printed, from the nearest text that names a unit."""
    for text in texts:
        scale = unit_scale(text)
        if scale is not None:
            m = UNIT_TEXT.search(text)
            return scale, m.group(0) if m else ("tCO2e" if scale == 1 else "")
    scale = page_unit or 1.0
    return scale, "tCO2e" if scale == 1 else ""


def extract_page(page, page_no: int, decimal: str) -> list[dict]:
    lines = read_lines(page)
    page_unit = dominant_unit_scale(page.get_text())
    header: list[tuple[int, Word]] = []
    stacked: list[tuple[int, Word]] = []   # some headers spread their years over two lines
    rows = []

    for i, line in enumerate(lines):
        years = year_columns(line)
        if years and len(figures(line, decimal)) <= 1 and len(line) <= 3 * len(years) + 8:
            stacked += years
            if len(stacked) >= 2:
                header = stacked
            continue
        stacked = []

        figs = figures(line, decimal)
        if not figs or not header:
            continue
        label = " ".join(w.text for w in line if w.x1 <= figs[0][0].x0)
        if len(label.split()) < 3 and i > 0 and not figures(lines[i - 1], decimal):
            label = " ".join(w.text for w in lines[i - 1]) + " " + label   # label wrapped onto two lines

        metrics = [m for m, d in TAXONOMY.items() if label_matches(d["rules"], label)]
        if len(metrics) != 1:
            continue

        nearby = [label, " ".join(str(y) for y, _ in header)]
        nearby += [" ".join(w.text for w in lines[j]) for j in range(i - 1, max(-1, i - 15), -1)]
        scale, unit_text = find_unit(nearby, page_unit)
        quote = " ".join(w.text for w in line)

        for cell, value in figs:
            year = column_year(cell, header)
            if year in YEARS:
                rows.append({"metric": metrics[0], "year": year, "value": value, "scale": scale,
                             "unit_as_printed": unit_text, "page": page_no, "quote": quote})
    return rows


def extract_company(ticker: str, file_name: str, language: str) -> list[dict]:
    path = RAW / file_name
    decimal = "," if language == "FR" else "."
    found = []
    with pymupdf.open(path) as doc:
        for rank, (page_no, _) in enumerate(rank_pages(path), 1):
            found += [{**r, "rank": rank} for r in extract_page(doc[page_no - 1], page_no, decimal)]

    # Several pages can repeat a figure (key figures, regional splits...). Trust the page
    # where the most metrics were found, which is usually the main E1-6 table.
    metrics_on_page: dict[int, set] = {}
    for r in found:
        metrics_on_page.setdefault(r["page"], set()).add(r["metric"])
    best: dict[tuple, dict] = {}
    for r in sorted(found, key=lambda r: (-len(metrics_on_page[r["page"]]), r["rank"])):
        best.setdefault((r["metric"], r["year"]), r)

    return [{"ticker": ticker, "metric": metric, "year": year, "value": r["value"],
             "unit_as_printed": r["unit_as_printed"], "page": r["page"], "quote": r["quote"],
             "value_tco2e": round(r["value"] * r["scale"])}
            for (metric, year), r in sorted(best.items())]


def main() -> None:
    rows = []
    for r in pd.read_csv(SOURCES).itertuples():
        if (RAW / r.file_name).exists():
            rows += extract_company(r.euronext_ticker, r.file_name, r.language)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)
    print(f"saved {len(df)} values for {df.ticker.nunique()} companies to {OUT}")


if __name__ == "__main__":
    main()
