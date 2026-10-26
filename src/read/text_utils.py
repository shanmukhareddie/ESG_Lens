"""Text helpers shared by the extraction and validation code."""

import re
import unicodedata

import yaml

SPACES = "    "                          # non-breaking and thin spaces
DASHES = "‐‑‒–—−"              # hyphens, en/em dash, minus sign
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
