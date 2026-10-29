"""Build the static ESG Lens site: one HTML page with the data embedded, no server needed.

Reads the pipeline's outputs (emissions, targets, portfolio metrics, scores) and fills
site/template.html. The result, site/index.html, can be opened from disk or served by
GitHub Pages.

Usage:
    python -m src.report.build_site
    python -m src.report.build_site --body-only page.html    # page content only, for embedding
"""

import argparse
import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

from src.portfolio.metrics import contributions, portfolio_metrics
from src.portfolio.metrics import load as load_holdings
from src.validate.evaluate import GOLD, summarize
from src.validate.reconcile import LLM, RULES, candidates, passed, precision_by_status

TEMPLATE = Path("site/template.html")
OUT = Path("site/index.html")
SOURCES = Path("data/cac40_fy2025_sources.csv")
COMPANIES = Path("data/companies.csv")
EMISSIONS = Path("data/processed/emissions.csv")
TARGETS = Path("data/processed/targets.csv")
QUEUE = Path("data/review/review_queue.csv")
SCORES = {
    "dev": ("Development set", "12 companies, used while building the extractors", "data/processed/evaluation.csv"),
    "test1": ("Test set 1", ("4 companies. Re-scored after fixing the two bugs they revealed, so no longer blind; "
                             "the first, blind run gave rules 28/46 and LLM 36/46"), "data/processed/test/evaluation.csv"),
    "test2": ("Test set 2", "4 new companies, scored once on the fixed extractors",
              "data/processed/test2/evaluation.csv"),
}
REPO = "https://github.com/shanmukhareddie/ESG_Lens"


def page_url(link: str, page) -> str:
    return f"{link}#page={int(page)}" if ".pdf" in link.lower() and pd.notna(page) else link


def clean(v):
    """JSON has no NaN."""
    return None if pd.isna(v) else v


def companies_data() -> list[dict]:
    sources = pd.read_csv(SOURCES).set_index("euronext_ticker")
    companies = pd.read_csv(COMPANIES).set_index("ticker")
    emissions = pd.read_csv(EMISSIONS)
    targets = pd.read_csv(TARGETS, dtype={"scope": str}) if TARGETS.exists() else pd.DataFrame(columns=["ticker"])
    queue = pd.read_csv(QUEUE) if QUEUE.exists() else pd.DataFrame(columns=["ticker"])
    waiting = queue.groupby("ticker").size()

    out = []
    for ticker, s in sources.iterrows():
        c = companies.loc[ticker]
        link = s["fy2025_link"]
        values = [{"metric": r.metric, "year": int(r.year), "value": r.value_tco2e, "status": r.status,
                   "page": int(r.page), "quote": r.quote, "url": page_url(link, r.page)}
                  for r in emissions[emissions["ticker"] == ticker].itertuples()]
        goals = [{"scope": r.scope, "base_year": clean(r.base_year), "target_year": int(r.target_year),
                  "pct": float(r.reduction_pct), "source": r.source, "page": int(r.page), "quote": r.quote,
                  "url": page_url(link, r.page)}
                 for r in targets[targets["ticker"] == ticker].itertuples()]
        out.append({
            "ticker": ticker, "name": s["company_full_name"], "short": s["company"],
            "sector": c["sector"], "subsector": c["subsector"], "country": c["country"],
            "revenue": clean(c["revenue"]), "market_cap": clean(c["market_cap"]), "employees": clean(c["employees"]),
            "report": link, "report_status": s["doc_status"], "waiting": int(waiting.get(ticker, 0)),
            "values": values, "targets": goals,
        })
    return sorted(out, key=lambda c: c["short"].lower())


def coverage_numbers(text: str) -> dict:
    return {k: int(v) / 100 for k, v in re.findall(r"(reported|estimated|missing) (\d+)%", text)}


def portfolio_data() -> dict:
    h = load_holdings()
    metrics = portfolio_metrics(h)
    financed = contributions(h).head(10).reset_index()

    s12 = h[["scope1_value", "scope2_value"]].astype(float).dropna()
    intensity = s12.sum(axis=1) / h.loc[s12.index, "revenue"]
    waci = (h.loc[s12.index, "weight"] * intensity)
    waci = (waci / waci.sum()).sort_values(ascending=False).head(10)

    return {
        "value": float(h["value_eur_m"].sum()),
        "metrics": [{"metric": r.metric, "value": r.value, "low": r.low, "high": r.high, "unit": r.unit,
                     "coverage": coverage_numbers(r.coverage)} for r in metrics.itertuples()],
        "financed": [{"ticker": r.ticker, "weight": r.weight, "tco2e": r.financed_tco2e, "share": r.share_of_financed}
                     for r in financed.itertuples()],
        "waci": [{"ticker": t, "weight": float(h.loc[t, "weight"]), "share": float(v)} for t, v in waci.items()],
    }


def accuracy_data() -> dict:
    sets = {}
    for key, (title, note, path) in SCORES.items():
        if not Path(path).exists():
            continue
        s = summarize(pd.read_csv(path), ["extractor"])
        sets[key] = {"title": title, "note": note, "rows": [
            {"extractor": r.extractor, "gold": int(r.gold), "correct": int(r.correct),
             "precision": clean(r.precision), "recall": r.recall} for r in s.itertuples()]}
    merge = precision_by_status(candidates(passed(RULES), passed(LLM)), pd.read_csv(GOLD))
    return {"sets": sets, "merge": merge.to_dict("records")}


def build() -> str:
    data = {
        "built": date.today().isoformat(),
        "repo": REPO,
        "companies": companies_data(),
        "portfolio": portfolio_data(),
        "accuracy": accuracy_data(),
    }
    payload = json.dumps(data, ensure_ascii=False, default=float).replace("</", "<\\/")
    return TEMPLATE.read_text().replace("__DATA__", payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--body-only", type=Path, help="also write the page content without the document wrapper")
    args = parser.parse_args()

    page = build()
    head, body = page.split("<!-- body -->")
    OUT.write_text(f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                   f'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                   f"{head}</head>\n<body>\n{body}</body>\n</html>\n")
    print(f"saved {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
    if args.body_only:
        args.body_only.write_text(page)
        print(f"saved {args.body_only}")


if __name__ == "__main__":
    main()
