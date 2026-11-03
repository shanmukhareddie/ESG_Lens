import numpy as np
import pandas as pd
import pytest

from src.estimate.model import (
    design_matrix,
    estimate_gaps,
    scores,
    sector_median_baseline,
)


def companies(n=16, seed=0):
    """Company-years whose emissions follow size and sector, with a little noise."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        sector = "Heavy" if i % 2 else "Light"
        log_revenue = rng.uniform(3, 5)
        for year in (2024, 2025):
            log_s3 = log_revenue + (2.5 if sector == "Heavy" else 1.5) + rng.normal(0, 0.1)
            rows.append({"ticker": f"C{i}", "year": year, "sector": sector, "log_revenue": log_revenue,
                         "log_employees": log_revenue - 1, "ghg_scope1": 10 ** (log_s3 - 2),
                         "ghg_scope2_market": 10 ** (log_s3 - 3), "ghg_scope3": 10 ** log_s3})
    return pd.DataFrame(rows)


def test_design_matrix_fills_employees_and_adds_scope12_only_for_scope3():
    df = companies()
    df.loc[0, "log_employees"] = np.nan
    X1 = design_matrix(df, "ghg_scope1")
    X3 = design_matrix(df, "ghg_scope3")
    assert not X1.isna().any().any()
    assert X1.loc[0, "employees_missing"] == 1 and X1["employees_missing"].sum() == 1
    assert "log_scope12" not in X1 and "log_scope12" in X3
    assert {"sector_Heavy", "sector_Light"} <= set(X1.columns)


def test_baseline_is_sector_intensity_times_revenue():
    df = companies()
    pred = sector_median_baseline(df.iloc[4:], df.iloc[:4], "ghg_scope3")
    assert np.abs(pred - np.log10(df["ghg_scope3"].iloc[:4])).max() < 0.5


def test_scores_on_a_hand_made_example():
    oof = pd.DataFrame({"y": [1.0, 2.0], "baseline": [1.5, 2.0], "ridge": [1.0, 2.2],
                        "ridge_p10": [0.5, 2.1], "ridge_p90": [1.5, 2.3],
                        "gbm": [1.0, 2.0], "gbm_p10": [0.9, 1.9], "gbm_p90": [1.1, 2.1]})
    s = scores(oof).set_index("model")
    assert s.loc["baseline", "mae_log10"] == pytest.approx(0.25)
    assert s.loc["ridge", "within_2x"] == 1.0          # both errors below log10(2)
    assert s.loc["ridge", "p10_p90_coverage"] == 0.5   # 2.0 is outside [2.1, 2.3]
    assert s.loc["gbm", "p10_p90_coverage"] == 1.0


def test_only_companies_missing_both_years_are_estimated():
    df = companies()
    df.loc[df["ticker"] == "C3", "ghg_scope3"] = np.nan                          # both years missing
    df.loc[(df["ticker"] == "C4") & (df["year"] == 2025), "ghg_scope3"] = np.nan  # one year missing
    out = estimate_gaps(df, "ghg_scope3")
    assert set(out["ticker"]) == {"C3"} and len(out) == 2
    assert (out["p10"] <= out["p50"]).all() and (out["p50"] <= out["p90"]).all()
    truth = 10 ** (df.loc[df["ticker"] == "C3", "log_revenue"].iloc[0] + 2.5)
    assert truth / 3 < out["p50"].iloc[0] < truth * 3


def test_nothing_to_estimate_gives_an_empty_table():
    assert estimate_gaps(companies(), "ghg_scope3").empty
