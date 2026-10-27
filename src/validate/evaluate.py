"""Score extractors against the hand-labelled gold set.

Each gold value is classified as correct, missed, wrong_year (the value of the other
year), wrong_unit (off by a factor of 1,000) or wrong_value.
    precision = correct / values the extractor returned
    recall    = correct / gold values

Usage:
    python -m src.validate.evaluate
    python -m src.validate.evaluate rules=data/processed/rules_extractions_checked.csv llm=...
"""

import argparse
import re
from pathlib import Path

import pandas as pd

GOLD = Path("data/gold/gold_labels.csv")
OUT = Path("data/processed/evaluation.csv")
DEFAULT_RUNS = {
    "rules": Path("data/processed/rules_extractions_checked.csv"),
    "llm": Path("data/processed/llm_extractions_checked.csv"),
}
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
    parser.add_argument("runs", nargs="*", help="name=path pairs; defaults to the rules and LLM outputs")
    args = parser.parse_args()
    runs = dict(r.split("=", 1) for r in args.runs) if args.runs else DEFAULT_RUNS

    gold = pd.read_csv(GOLD)
    results = []
    for name, path in runs.items():
        if Path(path).exists():
            results.append(evaluate(gold, pd.read_csv(path)).assign(extractor=name))
        else:
            print(f"skipping {name}: {path} not found")
    results = pd.concat(results, ignore_index=True)
    results.to_csv(OUT, index=False)

    pd.set_option("display.width", 160)
    print(summarize(results, ["extractor"]).to_string(index=False))
    print()
    print(summarize(results, ["extractor", "metric"]).to_string(index=False))
    print(f"\nrow-level results saved to {OUT}")


if __name__ == "__main__":
    main()
