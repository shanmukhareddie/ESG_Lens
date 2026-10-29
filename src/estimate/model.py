"""Estimate the emissions a company does not report, with an uncertainty range.

The target is log10(tCO2e): emissions span 1e2 to 1e8 tonnes, and an error of 0.3 in
log10 means "off by a factor of 2" for a small company and a large one alike.

Rows are company-years, so cross-validation must keep both years of a company in the
same fold (GroupKFold on ticker). Otherwise the model is tested on a company it has
already seen, and the scores look far better than they are.

Usage:
    python -m src.estimate.model --metric ghg_scope1
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from src.estimate.features import load

OUT = Path("data/processed/estimates.csv")
QUANTILES = (0.1, 0.5, 0.9)
N_FOLDS = 5


def design_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric features for the model.

    Decide: which size columns (log_revenue, log_employees, log_market_cap), how to encode
    sector (one-hot? subsector has too few companies per level), and what to do with the
    one company without employees (drop, impute, or a missing flag).
    """
    raise NotImplementedError


def sector_median_baseline(train: pd.DataFrame, test: pd.DataFrame, target: str) -> np.ndarray:
    """The simplest sensible estimate: median emissions per unit of revenue in the sector,
    times the company's revenue. Any model has to beat this to be worth having."""
    raise NotImplementedError


def fit_ridge(X: pd.DataFrame, y: pd.Series):
    """Linear baseline on log10 emissions. Scale the features; choose alpha by inner CV (RidgeCV)."""
    raise NotImplementedError


def fit_quantile_gbm(X: pd.DataFrame, y: pd.Series, quantile: float):
    """GradientBoostingRegressor(loss="quantile", alpha=quantile). With about 70 rows keep
    it small: shallow trees, few of them, a low learning rate, min_samples_leaf of 5 or more."""
    raise NotImplementedError


def cross_validate(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Out-of-fold predictions for every row that reports the target.

    For each GroupKFold split (groups = ticker): fit the baseline, ridge and the three
    quantile models on the train rows, predict the test rows. Return one row per
    company-year with the true value and each model's prediction, all in log10.
    """
    rows = df[df[target].notna()].reset_index(drop=True)
    folds = GroupKFold(n_splits=N_FOLDS).split(rows, groups=rows["ticker"])
    raise NotImplementedError(folds)


def scores(oof: pd.DataFrame) -> pd.DataFrame:
    """Per model: MAE in log10, the share of companies within a factor of 2 (|error| < 0.3),
    and for the quantile model the share of true values inside [P10, P90] (aim for about 80%)."""
    raise NotImplementedError


def estimate_gaps(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Refit on every reported row and predict the rows where the target is missing.
    Return ticker, year, metric, p10, p50, p90 in tCO2e (undo the log)."""
    raise NotImplementedError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metric", default="ghg_scope1")
    args = parser.parse_args()

    df = load()
    oof = cross_validate(df, args.metric)
    print(scores(oof).to_string(index=False))

    gaps = estimate_gaps(df, args.metric)
    if OUT.exists():   # one file for all metrics: replace only this metric's rows
        previous = pd.read_csv(OUT)
        gaps = pd.concat([previous[previous["metric"] != args.metric], gaps], ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    gaps.to_csv(OUT, index=False)
    print(f"estimated missing {args.metric} values, saved to {OUT}")


if __name__ == "__main__":
    main()
