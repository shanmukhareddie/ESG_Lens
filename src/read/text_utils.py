"""Text helpers shared by the extraction and validation code."""

import itertools
import re
import statistics
import unicodedata
from dataclasses import dataclass

import yaml

SPACES = "\u00a0\u202f\u2009\u2007"                          # non-breaking and thin spaces
DASHES = "\u2010\u2011\u2012\u2013\u2014\u2212"              # hyphens, en/em dash, minus sign
TAXONOMY_PATH = "src/read/taxonomy.yaml"


def normalize(text: str) -> str:
    """Lower-case, accent-free text with plain spaces and dashes, for regex matching."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("₂", "2")
    for d in DASHES:
        text = text.replace(d, "-")
    for s in SPACES:
        text = text.replace(s, " ")
    text = re.sub(r"(?i)co\s+2\b", "co2", text)   # "tCO 2 e" when the subscript is a separate word
    text = re.sub(r"(?i)\b(t|kt|mt)co\s+(e|eq)\b", r"\1co2\2", text)   # "tCO e" when the subscript was dropped
    return re.sub(r"\s+", " ", text).strip().lower()


def parse_number(token: str, decimal: str = ".") -> float | None:
    """Read a figure as printed in a report: '78,371,616', '1 234,5', '(1,234)', '2,087√'.

    `decimal` is the report's decimal mark ('.' in English, ',' in French).
    Returns None for anything that is not a plain figure, percentages included.
    """
    t = token.strip()
    for d in DASHES:
        t = t.replace(d, "-")
    for s in SPACES + " ":
        t = t.replace(s, "")
    t = re.sub(r"(?<=\d)(\(\w{1,2}\)|\*+|[√✓✔]+)$", "", t)   # footnote or audit tick
    if t.endswith("%"):
        return None
    negative = (t.startswith("(") and t.endswith(")")) or t.startswith("-")
    t = t.strip("()-+")
    if not re.fullmatch(r"\d[\d,.]*\d|\d", t):
        return None

    commas, dots = t.count(","), t.count(".")
    if commas and dots:
        # whichever separator comes last is the decimal mark
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif commas:
        thousands = all(len(g) == 3 for g in t.split(",")[1:])
        if decimal == "," and not (thousands and commas > 1):
            t = t.replace(",", ".") if commas == 1 else t
        elif thousands:
            t = t.replace(",", "")
        else:
            t = t.replace(",", ".")
    elif dots > 1 or (dots == 1 and decimal == "," and re.fullmatch(r"\d{1,3}\.\d{3}", t)):
        t = t.replace(".", "")

    try:
        value = float(t)
    except ValueError:
        return None
    return -value if negative else value


# Larger units first: "kt CO2" also contains "t CO2".
UNITS = [
    (1e6, [r"\bmt\s?co2", r"\bmtco2", r"\bmt\s?eq", r"millions?\s+(of\s+)?(metric\s+)?(t\b|tco2|tonnes|tons)",
           r"millions?\s+de\s+(t\b|tco2|tonnes)"]),
    (1e3, [r"\bkt\s?co2", r"\bktco2", r"\bkt\s?eq", r"\bkt\b", r"thousands?\s+(of\s+)?(metric\s+)?(t\b|tco2|tonnes|tons)",
           r"milliers?\s+de\s+(t\b|tco2|tonnes)", r"1[,. ]?000\s?x\s?(t\b|tons?|tonnes?)"]),
    (1.0, [r"\bt\s?co2", r"\btco2", r"\bteq\s?co2", r"\bt\s?eq", r"\btonnes?\s+(of\s+)?co2", r"\btons?\s+(of\s+)?co2"]),
]


def unit_scale(text: str) -> float | None:
    """Multiplier from the unit named in a short text (label, header) to tCO2e."""
    t = normalize(text)
    for factor, patterns in UNITS:
        if any(re.search(p, t) for p in patterns):
            return factor
    return None


def dominant_unit_scale(text: str) -> float | None:
    """Unit mentioned most often on a whole page; plain tonnes win a tie."""
    t = normalize(text)
    counts = {factor: sum(len(re.findall(p, t)) for p in patterns) for factor, patterns in UNITS}
    factor, n = max(counts.items(), key=lambda kv: (kv[1], kv[0] == 1.0))
    return factor if n else None


def load_taxonomy(path: str = TAXONOMY_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def label_matches(rules: dict, label: str) -> bool:
    t = normalize(label)
    return all(re.search(p, t) for p in rules["include"]) and not any(re.search(p, t) for p in rules["exclude"])


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


def layout_text(page, column_gap: float = 8) -> str:
    """Page text with each visual line kept together and ' | ' between table columns,
    so a reader can still see which figure sits under which year."""
    out = []
    for line in read_lines(page):
        parts = [line[0].text]
        for prev, w in itertools.pairwise(line):
            parts.append((" | " if w.x0 - prev.x1 > column_gap else " ") + w.text)
        out.append("".join(parts))
    return "\n".join(out)
