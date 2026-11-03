"""Score extractors against the hand-labelled gold set.

Each gold value is classified as correct, missed, wrong_year (the value of the other
year), wrong_unit (off by a factor of 1,000) or wrong_value.
    precision = correct / values the extractor returned
    recall    = correct / gold values

The labels come in three splits: dev (the 12 companies the extractors were built on),
test1 and test2 (held-out companies). All scores live in one file, data/processed/evaluation.csv:
a run replaces the rows of the split and extractors it scores and keeps the others, such as
llm_v1, the first prompt, whose output is no longer kept.

Usage:
    python -m src.validate.evaluate                    # dev split, rules and LLM
    python -m src.validate.evaluate --split test2
    python -m src.validate.evaluate --split dev rules=data/processed/rules_extractions.csv
"""

import argparse
import re
from pathlib import Path

import pandas as pd

GOLD = Path("data/gold/gold_labels.csv")
OUT = Path("data/processed/evaluation.csv")
DEFAULT_RUNS = {
    "rules": Path("data/processed/rules_extractions.csv"),
    "llm_v2": Path("data/processed/llm_extractions.csv"),
}
SPLITS = ["dev", "test1", "test2"]
KEY = ["ticker", "metric", "year"]


def tolerance(gold_value: float, unit_as_printed: str) -> float:
    """How far a prediction may be from the gold value and still count as correct.
    A figure printed in kt or Mt is rounded, so allow half of the last printed digit."""
    unit = unit_as_printed.lower()
    if re.search(r"\bmt\b|million", unit):
        rounding = 50_000            # Mt printed with one decimal
    elif re.search(r"\bkt|thousand|1000 x|milliers", unit):
        rounding = 500
    else:
        rounding = 0.5
    return max(0.005 * abs(gold_value), rounding)


def classify(pred: float, gold: float, other_year: float, tol: float) -> str:
    if pd.isna(pred):
        return "missed"
    if abs(pred - gold) <= tol:
        return "correct"
    if pd.notna(other_year) and abs(pred - other_year) <= tol:
        return "wrong_year"
    if gold and any(abs(pred - gold * f) <= tol * f for f in (1e3, 1e-3)):
        return "wrong_unit"
    return "wrong_value"


def evaluate(gold: pd.DataFrame, predictions: pd.DataFrame) -> pd.DataFrame:
    preds = predictions[KEY + ["value_tco2e"]].drop_duplicates(KEY).rename(columns={"value_tco2e": "predicted"})
    df = gold.merge(preds, on=KEY, how="left")
    other = gold.assign(year=gold["year"].map({2024: 2025, 2025: 2024}))[KEY + ["value_tco2e"]]
    df = df.merge(other.rename(columns={"value_tco2e": "other_year_value"}), on=KEY, how="left")
    df["outcome"] = [
        classify(r.predicted, r.value_tco2e, r.other_year_value, tolerance(r.value_tco2e, r.unit_as_printed))
        for r in df.itertuples()
    ]
    return df[KEY + ["value_tco2e", "predicted", "outcome", "pdf_page"]]


def summarize(results: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    def scores(g: pd.DataFrame) -> pd.Series:
        correct = (g["outcome"] == "correct").sum()
        returned = (g["outcome"] != "missed").sum()
        return pd.Series({
            "gold": len(g),
            "correct": correct,
            "precision": round(correct / returned, 3) if returned else None,
            "recall": round(correct / len(g), 3),
            **{k: (g["outcome"] == k).sum() for k in ("missed", "wrong_year", "wrong_unit", "wrong_value")},
        })
    return results.groupby(by).apply(scores, include_groups=False).reset_index()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="*", help="name=path pairs; defaults to the rules and the LLM")
    parser.add_argument("--split", default="dev", choices=SPLITS)
    args = parser.parse_args()
    runs = dict(r.split("=", 1) for r in args.runs) if args.runs else DEFAULT_RUNS

    gold = pd.read_csv(GOLD)
    gold = gold[gold["split"] == args.split]
    results = []
    for name, path in runs.items():
        if not Path(path).exists():
            print(f"skipping {name}: {path} not found")
            continue
        results.append(evaluate(gold, pd.read_csv(path)).assign(extractor=name, split=args.split))
    results = pd.concat(results, ignore_index=True)

    if OUT.exists():   # keep the scores of other splits and extractors
        kept = pd.read_csv(OUT)
        kept = kept[~((kept["split"] == args.split) & kept["extractor"].isin(results["extractor"]))]
        results_all = pd.concat([kept, results], ignore_index=True)
    else:
        results_all = results
    order = {s: i for i, s in enumerate(SPLITS)}
    results_all = results_all.sort_values(["split", "extractor"] + KEY, key=lambda c: c.map(order) if c.name == "split" else c)
    results_all.to_csv(OUT, index=False)

    pd.set_option("display.width", 160)
    print(f"{args.split} split, {gold['ticker'].nunique()} companies, {len(gold)} values")
    print(summarize(results, ["extractor"]).to_string(index=False))
    print()
    print(summarize(results, ["extractor", "metric"]).to_string(index=False))
    print(f"\nrow-level results saved to {OUT}")


if __name__ == "__main__":
    main()
