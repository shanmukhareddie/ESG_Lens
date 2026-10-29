"""Combine the rules and LLM extractions into one emissions table.

For each (ticker, metric, year):
    verified    the value was labelled by hand (gold set or test set)
    agreed      both extractors found it, with the same value
    rules_only / llm_only   only one extractor found it
    conflict    both found it, with different values

Only values that passed the evidence checks are used. On the gold companies agreed and
single-source values were right 98-100% of the time, while in a conflict either side was
right less than half the time. So everything is accepted except conflicts and values whose
company-year fails the accounting check (total = Scope 1 + 2 + 3). Those go to
data/review/review_queue.csv, where a person fills `decision`:
    rules | llm     take that extractor's value
    manual          take value_tco2e and page as typed in the queue
    none            the figure is not reported
Decisions already made are kept when the queue is rebuilt. When both extractors may be wrong
in the same way (Vinci prints a baseline-year column before 2025, and both read it as 2025),
`--review` sends every extracted value of a company to the queue, and it stays there.

Usage:
    python -m src.validate.reconcile
    python -m src.validate.reconcile --review DG
"""

import argparse
from pathlib import Path

import pandas as pd

from src.read.find_pages import SOURCES
from src.validate.evaluate import GOLD, KEY, classify, tolerance

RULES = Path("data/processed/rules_extractions.csv")
LLM = Path("data/processed/llm_extractions.csv")
TEST_LABELS = Path("data/gold/test_labels.csv")
QUEUE = Path("data/review/review_queue.csv")
OUT = Path("data/processed/emissions.csv")

SOURCE_COLS = ["value_tco2e", "page", "quote"]
TOTALS = {"ghg_total_location": "ghg_scope2_location", "ghg_total_market": "ghg_scope2_market"}


def passed(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["evidence_ok"].astype(bool)].dropna(subset=["value_tco2e"])
    return df.drop_duplicates(KEY)[KEY + SOURCE_COLS]


def same_value(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.005 * max(abs(a), abs(b)), 1)


def candidates(rules: pd.DataFrame, llm: pd.DataFrame) -> pd.DataFrame:
    df = rules.merge(llm, on=KEY, how="outer", suffixes=("_rules", "_llm"))
    has_rules, has_llm = df["value_tco2e_rules"].notna(), df["value_tco2e_llm"].notna()
    df["status"] = "llm_only"
    df.loc[has_rules & ~has_llm, "status"] = "rules_only"
    both = has_rules & has_llm
    agree = [same_value(a, b) for a, b in zip(df.loc[both, "value_tco2e_rules"], df.loc[both, "value_tco2e_llm"])]
    df.loc[both, "status"] = ["agreed" if a else "conflict" for a in agree]
    return df


def precision_by_status(df: pd.DataFrame, gold: pd.DataFrame) -> pd.DataFrame:
    """How often each status is right, measured on the gold companies. This is what
    justifies accepting agreed values without a look."""
    g = gold[KEY + ["value_tco2e", "unit_as_printed"]].rename(columns={"value_tco2e": "gold"})
    m = df.merge(g, on=KEY)
    rows = []
    for r in m.itertuples():
        tol = tolerance(r.gold, r.unit_as_printed)
        for side in ("rules", "llm"):
            value = getattr(r, f"value_tco2e_{side}")
            if pd.notna(value):
                rows.append({"status": r.status, "extractor": side,
                             "correct": classify(value, r.gold, None, tol) == "correct"})
    out = pd.DataFrame(rows).groupby(["status", "extractor"])["correct"].agg(["size", "mean"])
    return out.rename(columns={"size": "values", "mean": "precision"}).round(3).reset_index()


def has_key(df: pd.DataFrame, other: pd.DataFrame):
    return df.set_index(KEY).index.isin(other.set_index(KEY).index)


def earlier_review() -> pd.DataFrame:
    """Rows a person has decided or asked to review: they stay in the queue on every run."""
    if not QUEUE.exists():
        return pd.DataFrame(columns=KEY + ["reason"])
    q = pd.read_csv(QUEUE, dtype={"decision": str})
    decided = q["decision"].fillna("").str.strip() != ""
    return q[decided | (q["reason"] == "sent to review")]


def review_queue(df: pd.DataFrame) -> pd.DataFrame:
    queue = df[df["needs_review"]].copy()
    queue["decision"] = ""
    queue["value_tco2e"] = pd.NA
    queue["page"] = pd.NA
    if QUEUE.exists():   # keep what has already been reviewed
        done = pd.read_csv(QUEUE, dtype={"decision": str})
        done = done[done["decision"].notna() & (done["decision"].str.strip() != "")]
        queue = queue.set_index(KEY)
        done = done.set_index(KEY)[["decision", "value_tco2e", "page"]]
        queue.update(done)
        queue = queue.reset_index()
    cols = KEY + ["status", "reason", "decision", "value_tco2e", "page"]
    cols += [f"{c}_{s}" for s in ("rules", "llm") for c in SOURCE_COLS]
    return queue[cols].sort_values(KEY)


def pick(r, side: str) -> dict:
    return {"value_tco2e": r[f"value_tco2e_{side}"], "page": r[f"page_{side}"], "quote": r[f"quote_{side}"]}


def accepted(df: pd.DataFrame, queue: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df[~df["needs_review"]].iterrows():
        side = "llm" if r["status"] == "llm_only" else "rules"
        rows.append({**{k: r[k] for k in KEY}, **pick(r, side), "status": r["status"]})
    for _, r in queue.iterrows():
        decision = str(r["decision"]).strip().lower()
        if decision in ("rules", "llm"):
            rows.append({**{k: r[k] for k in KEY}, **pick(r, decision), "status": "reviewed"})
        elif decision == "manual":
            quote = r["quote_rules"] if pd.notna(r["quote_rules"]) else r["quote_llm"]
            rows.append({**{k: r[k] for k in KEY}, "value_tco2e": r["value_tco2e"], "page": r["page"],
                         "quote": quote, "status": "reviewed"})
    out = pd.DataFrame(rows)

    verified = labels.rename(columns={"pdf_page": "page", "row_text": "quote"})[KEY + SOURCE_COLS]
    verified = verified.assign(status="verified")
    out = pd.concat([verified, out[~out.set_index(KEY).index.isin(verified.set_index(KEY).index)]])
    return out.sort_values(KEY).reset_index(drop=True)


def identity_check(df: pd.DataFrame, slack: float = 0.05) -> pd.Series:
    """True where a total equals Scope 1 + Scope 2 + Scope 3 within 5%, None where a part is missing."""
    wide = df.pivot_table(index=["ticker", "year"], columns="metric", values="value_tco2e")
    result = pd.Series(pd.NA, index=df.index, dtype="boolean")
    for total, scope2 in TOTALS.items():
        needed = ["ghg_scope1", scope2, "ghg_scope3", total]
        if not set(needed) <= set(wide.columns):
            continue
        parts = wide[["ghg_scope1", scope2, "ghg_scope3"]].sum(axis=1, min_count=3)
        ok = ((wide[total] - parts).abs() <= slack * wide[total]).where(parts.notna() & wide[total].notna())
        for (ticker, year), value in ok.dropna().items():
            rows = (df["ticker"] == ticker) & (df["year"] == year) & df["metric"].isin(needed)
            result[rows] = bool(value)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", nargs="+", default=[], metavar="TICKER",
                        help="send every extracted value of these companies to the review queue")
    args = parser.parse_args()

    gold = pd.read_csv(GOLD)
    labels = pd.concat([gold, pd.read_csv(TEST_LABELS)])
    labels = labels[labels["ticker"].isin(pd.read_csv(SOURCES)["euronext_ticker"])]   # CAC 40 only
    df = candidates(passed(RULES), passed(LLM))

    print("precision on the gold companies, by status:")
    print(precision_by_status(df, gold).to_string(index=False))

    df = df[~has_key(df, labels)].reset_index(drop=True)
    kept = earlier_review()
    df["reason"] = ""
    df.loc[df["status"] == "conflict", "reason"] = "extractors disagree"
    sent = df["ticker"].isin(args.review) | has_key(df, kept[kept["reason"] == "sent to review"])
    df.loc[sent & (df["reason"] == ""), "reason"] = "sent to review"
    df.loc[has_key(df, kept) & (df["reason"] == ""), "reason"] = "decided earlier"
    df["needs_review"] = df["reason"] != ""

    # a first pass without review, to find the company-years whose figures do not add up
    first = accepted(df, review_queue(df.iloc[:0]), labels)
    first = first[(first["status"] != "verified") & identity_check(first).eq(False)]
    df.loc[has_key(df, first) & (df["reason"] == ""), "reason"] = "total != S1 + S2 + S3"
    df["needs_review"] = df["reason"] != ""

    queue = review_queue(df)
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    queue.to_csv(QUEUE, index=False)

    final = accepted(df, queue, labels)
    final["identity_ok"] = identity_check(final)
    final.to_csv(OUT, index=False)

    pending = (queue["decision"].fillna("").astype(str).str.strip() == "").sum()
    print(f"\n{len(final)} values for {final['ticker'].nunique()} companies saved to {OUT}")
    print(final["status"].value_counts().to_string())
    print(f"{pending} of {len(queue)} values in {QUEUE} still need a decision")
    print(f"identity check failed for {final['identity_ok'].eq(False).sum()} values")


if __name__ == "__main__":
    main()
