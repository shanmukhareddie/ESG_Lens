"""Extract climate targets (ESRS E1-4) with an LLM and score them against the labelled ones.

A target here is an absolute cut in the company's own Scope 1, 2 or 3 emissions, as a
percentage, by a target year, against a base year. Intensity targets, financed-emissions
targets of banks and insurers, and net-zero pledges without a percentage are left out, as
in data/gold/gold_targets.csv.

Outputs:
    data/processed/targets_llm.csv   every target the LLM returned, with evidence checks
    data/processed/targets.csv       the final table: labelled targets where a company has
                                     them, otherwise the extracted ones that pass the checks

Usage:
    python -m src.read.targets_extract                  # every report
    python -m src.read.targets_extract --tickers BN OR
"""

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Literal

import groq
import pandas as pd
import pymupdf
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from src.read.find_pages import RAW, SOURCES
from src.read.llm_extract import MODEL, PAUSE, ask
from src.read.text_utils import layout_text, normalize
from src.validate.evidence import page_text, pdf_files, quote_on_page

GOLD = Path("data/gold/gold_targets.csv")
CACHE = Path("data/llm_cache/targets")
RAW_OUT = Path("data/processed/targets_llm.csv")
OUT = Path("data/processed/targets.csv")
PAGES_PER_REPORT = 4
PROMPT_BUDGET = 12000
KEY = ["ticker", "scope", "target_year"]

# A page only has to look like a target page; the model decides what is a target.
SIGNALS = [
    (r"\be1-4\b", 3),
    (r"\b(targets?|objectifs?|ambition|aims? to|commit\w*)\b", 1),
    (r"\b(reduc\w+|baisse|diminu\w+)\b", 1),
    (r"\b(base(line)? year|baseline|compared (to|with)|relative to|par rapport|annee de reference|from a 20\d\d)\b", 2),
    (r"\b20(30|35|40|45|50)\b", 1),
    (r"scopes?\s?1", 1),
    (r"scopes?\s?3", 1),
    (r"-?\d{1,2}(\.\d)?\s?%", 1),
    (r"\babsolu(te)?\b", 1),
    (r"\bsbti\b|science based", 1),
]
KEEP_LINE = re.compile(r"\d|scope|target|objecti|reduc|baisse|absolu|baseline|base year|compared|relative|"
                       r"sbti|science|net.zero|emission|ghg|ges|carbon|co2", re.IGNORECASE)

SYSTEM_PROMPT = """Act as a Data Scientist and extract the climate targets from the sustainability statement of a company's annual report (ESRS E1-4).

Pages are given line by line, with " | " between table columns.

A target to extract is an ABSOLUTE reduction of the company's own greenhouse gas emissions
(Scope 1, Scope 2 and/or Scope 3) by a percentage, by a target year after 2025. Do not extract:
- intensity targets (per unit of revenue, product, tonne, passenger, square metre...),
- targets on financed, insured or portfolio emissions (banks, insurers, asset managers),
- energy, renewable-electricity or energy-efficiency targets,
- net-zero or carbon-neutrality pledges with no percentage,
- progress already achieved (e.g. "-21.6% since 2019").

Return only a JSON object: {"targets": [...]}. Each target has exactly these fields:
  scope          which scopes it covers: "1", "2", "1+2", "3", "1+3" or "1+2+3"
                 (a Scope 3 target limited to some categories is still "3";
                 a FLAG target on Scope 1 and 3 is "1+3")
  base_year      the base year, or null if none is printed
  target_year    the year the target must be reached
  reduction_pct  the percentage cut, as a positive number: "-46.3%" -> 46.3
  page           the number in the "=== PAGE n ===" marker of the page you read it from
  quote          the sentence or table row copied word for word from the page

Return each target once, even if the report repeats it. If there is none, return {"targets": []}."""


class TargetRecord(BaseModel):
    ticker: str
    scope: Literal["1", "2", "1+2", "3", "1+3", "1+2+3"]
    base_year: int | None = Field(default=None, ge=1990, le=2025)
    target_year: int = Field(ge=2026, le=2060)
    reduction_pct: float = Field(gt=0, le=100)
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)


def score_page(text: str) -> int:
    t = normalize(text)
    return sum(weight for pattern, weight in SIGNALS if re.search(pattern, t))


def rank_target_pages(file_name: str, n: int = PAGES_PER_REPORT) -> list[int]:
    with pymupdf.open(RAW / file_name) as doc:
        scores = sorted(((score_page(p.get_text()), i + 1) for i, p in enumerate(doc)), key=lambda s: (-s[0], s[1]))
    return [page for _, page in scores[:n]]


def target_pages(file_name: str, n: int = PAGES_PER_REPORT) -> list[tuple[int, str]]:
    with pymupdf.open(RAW / file_name) as doc:
        return [(p, layout_text(doc[p - 1])) for p in rank_target_pages(file_name, n)]


def build_prompt(company: str, pages: list[tuple[int, str]]) -> str:
    parts, used = [], 0
    for page, text in pages:
        lines = [ln.strip() for ln in text.splitlines()]
        block = f"=== PAGE {page} ===\n" + "\n".join(ln for ln in lines if len(ln) > 3 and KEEP_LINE.search(ln))
        if parts and used + len(block) > PROMPT_BUDGET:
            break
        parts.append(block[:PROMPT_BUDGET])
        used += len(block)
    return f"Company: {company}\n\nPages:\n" + "\n\n".join(parts)


def parse(ticker: str, raw: str) -> tuple[list[TargetRecord], list[str]]:
    try:
        items = json.loads(raw).get("targets", [])
    except json.JSONDecodeError as e:
        return [], [f"invalid JSON: {e}"]
    records, errors = [], []
    for item in items:
        try:
            records.append(TargetRecord(ticker=ticker, **item))
        except (ValidationError, TypeError) as e:
            errors.append(f"{item}: {e}")
    return records, errors


def extract(client: groq.Groq, ticker: str, company: str, file_name: str) -> list[TargetRecord]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(company, target_pages(file_name))}]
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
                     {"role": "user", "content": "Some targets were invalid:\n" + "\n".join(errors[:10])
                      + "\nReturn the full corrected JSON object."}]
        raw = ask(client, messages)
        records, errors = parse(ticker, raw)
        if errors:
            print(f"  {ticker}: {len(errors)} targets still invalid and dropped")

    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"key": key, "model": MODEL, "response": raw}, indent=1))
    return records


def pct_in_quote(pct: float, quote: str) -> bool:
    p = f"{pct:g}"
    return any(re.search(r"(?<![\d.,])" + re.escape(x) + r"\s?%", quote) for x in (p, p.replace(".", ",")))


def locate(ticker: str, quote: str, page: int) -> int | None:
    """The page the quote is printed on. The model sometimes names another of the pages it was
    given (a target is often repeated), so those are searched too."""
    for p in [page] + [p for p in rank_target_pages(pdf_files()[ticker]) if p != page]:
        text = page_text(ticker, p)
        if text is not None and quote_on_page(quote, text):
            return p
    return None


def check(df: pd.DataFrame) -> pd.DataFrame:
    """A target is kept when its quote is printed in the report and contains its percentage."""
    df = df.copy()
    found = [locate(t, q, int(p)) for t, q, p in zip(df["ticker"], df["quote"], df["page"])]
    df["quote_on_page"] = [p is not None for p in found]
    df["page"] = [p if p is not None else page for p, page in zip(found, df["page"])]
    df["pct_in_quote"] = [pct_in_quote(p, q) for p, q in zip(df["reduction_pct"], df["quote"])]
    df["evidence_ok"] = df["quote_on_page"] & df["pct_in_quote"]
    return df


def evaluate(gold: pd.DataFrame, extracted: pd.DataFrame) -> pd.DataFrame:
    """One row per labelled target: found with the right percentage, found with another one, or missed."""
    pred = extracted[extracted["evidence_ok"]].drop_duplicates(KEY)
    df = gold.merge(pred[KEY + ["reduction_pct", "base_year"]], on=KEY, how="left", suffixes=("", "_pred"))
    df["outcome"] = "missed"
    found = df["reduction_pct_pred"].notna()
    df.loc[found, "outcome"] = "wrong_pct"
    df.loc[found & ((df["reduction_pct_pred"] - df["reduction_pct"]).abs() <= 0.5), "outcome"] = "correct"
    df["base_year_ok"] = df["base_year_pred"] == df["base_year"]
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="+")
    args = parser.parse_args()

    load_dotenv()
    client = groq.Groq()
    sources = pd.read_csv(SOURCES)
    if args.tickers:
        sources = sources[sources["euronext_ticker"].isin(args.tickers)]

    rows = []
    for r in sources.itertuples():
        if not (RAW / r.file_name).exists():
            continue
        records = extract(client, r.euronext_ticker, r.company_full_name, r.file_name)
        rows += [rec.model_dump() for rec in records]
        print(f"{r.euronext_ticker:6s} {len(records)} targets", flush=True)
        time.sleep(PAUSE)

    extracted = check(pd.DataFrame(rows))
    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    extracted.to_csv(RAW_OUT, index=False)
    print(f"saved {len(extracted)} targets to {RAW_OUT}, {extracted['evidence_ok'].sum()} pass the evidence checks")

    gold = pd.read_csv(GOLD)
    scored = evaluate(gold, extracted)
    on_gold = extracted[extracted["evidence_ok"] & extracted["ticker"].isin(gold["ticker"])].drop_duplicates(KEY)
    correct = (scored["outcome"] == "correct").sum()
    print(f"\nlabelled targets: {len(gold)}, found correctly: {correct} (recall {correct / len(gold):.0%}), "
          f"precision {correct / max(len(on_gold), 1):.0%} of {len(on_gold)} returned for those companies, "
          f"base year right for {scored['base_year_ok'].sum()}")
    print(scored[scored["outcome"] != "correct"][KEY + ["reduction_pct", "reduction_pct_pred", "outcome"]].to_string(index=False))

    labelled = gold.rename(columns={"pdf_page": "page", "row_text": "quote"}).assign(source="labelled")
    others = extracted[extracted["evidence_ok"] & ~extracted["ticker"].isin(gold["ticker"])].drop_duplicates(KEY)
    final = pd.concat([labelled, others.assign(source="extracted")])[
        ["ticker", "scope", "base_year", "target_year", "reduction_pct", "page", "quote", "source"]]
    final = final.sort_values(["ticker", "target_year", "scope"]).reset_index(drop=True)
    final.to_csv(OUT, index=False)
    print(f"\n{len(final)} targets for {final['ticker'].nunique()} companies saved to {OUT}")


if __name__ == "__main__":
    main()
