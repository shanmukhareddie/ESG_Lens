"""Estimate the emissions a company does not report, with an uncertainty range.

The target is log10(tCO2e): emissions span 1e2 to 1e8 tonnes, and an error of 0.3 in
log10 means "off by a factor of 2" for a small company and a large one alike.

Rows are company-years, so cross-validation must keep both years of a company in the
same fold (GroupKFold on ticker). Otherwise the model is tested on a company it has
already seen, and the scores look far better than they are.

Only companies that report the metric in neither year are estimated. When a company
reports it for the other year, that figure is a far better guess than any model
(emissions move about 5% a year), and the portfolio metrics already fall back to it.

Usage:
    python -m src.estimate.model --metric ghg_scope3
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.estimate.features import load

OUT = Path("data/processed/estimates.csv")
QUANTILES = (0.1, 0.5, 0.9)
N_FOLDS = 5
ALPHAS = np.logspace(-2, 3, 11)


def own_scope12(df: pd.DataFrame) -> pd.Series:
    """log10 of the company's reported Scope 1 + Scope 2 (market), taken from its other
    year when this year's is missing."""
    s12 = df["ghg_scope1"] + df["ghg_scope2_market"]
    return np.log10(s12.fillna(s12.groupby(df["ticker"]).transform("mean")))


def design_matrix(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Size and sector, one row per company-year, plus the company's own Scope 1 + 2 when
    the target is Scope 3 (it cuts the error from a factor of 3.4 to 2.6).

    Market cap is left out: it hardly correlates with emissions (r below 0.25 for every
    scope). Subsector is left out too, with about 35 companies it is one company per level.
    A company without an employee count gets its sector's median, plus a flag.
    """
    X = df[["log_revenue", "log_employees"]].copy()
    X["employees_missing"] = X["log_employees"].isna().astype(float)
    sector_median = df.groupby("sector")["log_employees"].transform("median")
    X["log_employees"] = X["log_employees"].fillna(sector_median).fillna(df["log_employees"].median())
    if target == "ghg_scope3":
        s12 = own_scope12(df)
        X["log_scope12"] = s12.fillna(s12.median())
    return pd.concat([X, pd.get_dummies(df["sector"], prefix="sector", dtype=float)], axis=1)


def sector_median_baseline(train: pd.DataFrame, test: pd.DataFrame, target: str) -> np.ndarray:
    """The simplest sensible estimate: the sector's median emissions per euro of revenue,
    times the company's revenue. Any model has to beat this to be worth having."""
    intensity = np.log10(train[target]) - train["log_revenue"]
    by_sector = intensity.groupby(train["sector"]).median()
    return (test["sector"].map(by_sector).fillna(intensity.median()) + test["log_revenue"]).to_numpy()


def fit_ridge(X: pd.DataFrame, y: pd.Series, groups: pd.Series):
    """Linear model on log10 emissions, alpha chosen by grouped inner cross-validation.
    (RidgeCV's leave-one-out would keep the other year of the same company in training.)"""
    def cv_error(alpha: float) -> float:
        errors = []
        for train, test in GroupKFold(n_splits=N_FOLDS).split(X, groups=groups):
            m = make_pipeline(StandardScaler(), Ridge(alpha=alpha)).fit(X.iloc[train], y.iloc[train])
            errors.append(np.abs(m.predict(X.iloc[test]) - y.iloc[test]))
        return float(np.concatenate(errors).mean())

    best = min(ALPHAS, key=cv_error)
    return make_pipeline(StandardScaler(), Ridge(alpha=best)).fit(X, y)


def ridge_interval(X: pd.DataFrame, y: pd.Series, groups: pd.Series) -> np.ndarray:
    """Offsets for P10 and P90 around the ridge prediction: the 10th and 90th percentiles of
    its own out-of-fold errors on the training rows."""
    residuals = []
    for train, test in GroupKFold(n_splits=N_FOLDS).split(X, groups=groups):
        m = fit_ridge(X.iloc[train], y.iloc[train], groups.iloc[train])
        residuals.append(y.iloc[test] - m.predict(X.iloc[test]))
    return np.quantile(np.concatenate(residuals), [0.1, 0.9])


def fit_quantile_gbm(X: pd.DataFrame, y: pd.Series, quantile: float):
    """Gradient boosting with quantile loss, kept small for about 70 rows."""
    return GradientBoostingRegressor(loss="quantile", alpha=quantile, n_estimators=150, max_depth=2,
                                     learning_rate=0.05, min_samples_leaf=5, subsample=0.8,
                                     random_state=0).fit(X, y)


def gbm_quantiles(X: pd.DataFrame, y: pd.Series, X_new: pd.DataFrame) -> np.ndarray:
    """P10, P50 and P90 per row, sorted: separate quantile models can cross."""
    return np.sort(np.column_stack([fit_quantile_gbm(X, y, q).predict(X_new) for q in QUANTILES]), axis=1)


def cross_validate(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Out-of-fold predictions, in log10, for every company-year that reports the target."""
    has = df[target].notna()
    rows = df[has]
    X, y, groups = design_matrix(df, target)[has], np.log10(rows[target]), rows["ticker"]

    out = []
    for train, test in GroupKFold(n_splits=N_FOLDS).split(X, groups=groups):
        X_tr, y_tr, g_tr, X_te = X.iloc[train], y.iloc[train], groups.iloc[train], X.iloc[test]
        point = fit_ridge(X_tr, y_tr, g_tr).predict(X_te)
        low, high = ridge_interval(X_tr, y_tr, g_tr)
        gbm = gbm_quantiles(X_tr, y_tr, X_te)
        out.append(pd.DataFrame({
            "ticker": groups.iloc[test].to_numpy(),
            "year": rows["year"].iloc[test].to_numpy(),
            "y": y.iloc[test].to_numpy(),
            "baseline": sector_median_baseline(rows.iloc[train], rows.iloc[test], target),
            "ridge": point, "ridge_p10": point + low, "ridge_p90": point + high,
            "gbm": gbm[:, 1], "gbm_p10": gbm[:, 0], "gbm_p90": gbm[:, 2],
        }))
    return pd.concat(out, ignore_index=True)


def scores(oof: pd.DataFrame) -> pd.DataFrame:
    """Per model: mean absolute error in log10, share of estimates within a factor of 2,
    and for the two models with a range, the share of true values inside P10-P90 (should be
    near 80%) and the typical width of that range, as a ratio P90 / P10."""
    rows = []
    for model in ("baseline", "ridge", "gbm"):
        err = (oof[model] - oof["y"]).abs()
        row = {"model": model, "mae_log10": err.mean(), "within_2x": (err < np.log10(2)).mean()}
        if f"{model}_p10" in oof:
            row["p10_p90_coverage"] = oof["y"].between(oof[f"{model}_p10"], oof[f"{model}_p90"]).mean()
            row["p90_over_p10"] = 10 ** (oof[f"{model}_p90"] - oof[f"{model}_p10"]).median()
        rows.append(row)
    return pd.DataFrame(rows).round(3)


def estimate_gaps(df: pd.DataFrame, target: str, model: str = "ridge") -> pd.DataFrame:
    """Fit on every reported row and estimate the companies that report the target in
    neither year. Returns ticker, year, metric, model, p10, p50, p90 in tCO2e."""
    reported = df.groupby("ticker")[target].transform("count") > 0
    has, todo = df[target].notna(), ~reported
    columns = ["ticker", "year", "metric", "model", "p10", "p50", "p90"]
    if not todo.any():
        return pd.DataFrame(columns=columns)

    X = design_matrix(df, target)
    y, groups = np.log10(df.loc[has, target]), df.loc[has, "ticker"]
    if model == "ridge":
        p50 = fit_ridge(X[has], y, groups).predict(X[todo])
        low, high = ridge_interval(X[has], y, groups)
        p10, p90 = p50 + low, p50 + high
    else:
        p10, p50, p90 = gbm_quantiles(X[has], y, X[todo]).T

    out = df.loc[todo, ["ticker", "year"]].assign(metric=target, model=model,
                                                  p10=10 ** p10, p50=10 ** p50, p90=10 ** p90)
    return out[columns].round({"p10": 0, "p50": 0, "p90": 0})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metric", default="ghg_scope3")
    args = parser.parse_args()

    df = load()
    result = scores(cross_validate(df, args.metric))
    print(f"{args.metric}: out-of-fold scores, {df[args.metric].notna().sum()} company-years")
    print(result.to_string(index=False))

    # the model with a range and the smaller error makes the estimates
    model = result[result["model"] != "baseline"].sort_values("mae_log10").iloc[0]["model"]
    gaps = estimate_gaps(df, args.metric, model)
    if OUT.exists():   # one file for all metrics: replace only this metric's rows
        previous = pd.read_csv(OUT)
        gaps = pd.concat([previous[previous["metric"] != args.metric], gaps], ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    gaps.to_csv(OUT, index=False)
    print(f"\n{model} estimates for {args.metric}, saved to {OUT}:")
    print(gaps[gaps["metric"] == args.metric].to_string(index=False))


if __name__ == "__main__":
    main()
