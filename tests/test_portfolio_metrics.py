import pandas as pd
import pytest

from src.portfolio.metrics import (
    cap_weighted,
    holdings,
    portfolio_metrics,
    scope_values,
)

COMPANIES = pd.DataFrame({
    "ticker": ["A", "B", "C"],
    "market_cap": [900.0, 400.0, 100.0],
    "total_debt": [100.0, 0.0, 0.0],
    "minority_interest": [0.0, 100.0, 0.0],      # EVIC: A 1000, B 500, C 100
    "revenue": [500.0, 100.0, 50.0],
})
EMISSIONS = pd.DataFrame({
    "ticker": ["A", "A", "A", "B", "B"],
    "metric": ["ghg_scope1", "ghg_scope2_market", "ghg_scope3", "ghg_scope1", "ghg_scope2_market"],
    "year": [2025, 2025, 2025, 2025, 2024],
    "value_tco2e": [100.0, 50.0, 1000.0, 10.0, 0.0],
})
ESTIMATES = pd.DataFrame({"ticker": ["B"], "metric": ["ghg_scope3"], "year": [2025],
                          "p10": [100.0], "p50": [200.0], "p90": [400.0]})


def run(portfolio):
    h = holdings(portfolio, COMPANIES, scope_values(EMISSIONS, ESTIMATES))
    return portfolio_metrics(h).set_index("metric")


def test_cap_weighted_portfolio_adds_up():
    p = cap_weighted(COMPANIES, total=100)
    assert p["value_eur_m"].sum() == pytest.approx(100)
    assert p.set_index("ticker").loc["A", "value_eur_m"] == pytest.approx(900 / 1400 * 100)


def test_sources_reported_prior_year_and_estimated():
    s = scope_values(EMISSIONS, ESTIMATES).set_index(["ticker", "scope"])["source"]
    assert s[("A", "scope1")] == "reported"
    assert s[("B", "scope2")] == "reported_prior_year"
    assert s[("B", "scope3")] == "estimated"
    assert ("C", "scope1") not in s.index


def test_metrics_match_a_hand_calculation():
    m = run(pd.DataFrame({"ticker": ["A", "B"], "value_eur_m": [30.0, 10.0]}))   # weights 0.75, 0.25
    assert m.loc["PAI 1 scope 1", "value"] == pytest.approx(30 / 1000 * 100 + 10 / 500 * 10)
    assert m.loc["PAI 1 total", "value"] == pytest.approx(30 / 1000 * 1150 + 10 / 500 * 210)
    assert m.loc["PAI 1 total", "low"] == pytest.approx(30 / 1000 * 1150 + 10 / 500 * 110)
    assert m.loc["PAI 1 total", "high"] == pytest.approx(30 / 1000 * 1150 + 10 / 500 * 410)
    assert m.loc["PAI 2 carbon footprint", "value"] == pytest.approx(38.7 / 40)
    assert m.loc["PAI 3 GHG intensity", "value"] == pytest.approx(0.75 * 1150 / 500 + 0.25 * 210 / 100)
    assert m.loc["WACI (scope 1+2)", "value"] == pytest.approx(0.75 * 150 / 500 + 0.25 * 10 / 100)
    assert m.loc["PAI 1 total", "coverage"] == "reported 75%, estimated 25%, missing 0%"


def test_holding_without_data_is_left_out_of_ratios():
    with_c = run(pd.DataFrame({"ticker": ["A", "B", "C"], "value_eur_m": [30.0, 10.0, 60.0]}))
    without_c = run(pd.DataFrame({"ticker": ["A", "B"], "value_eur_m": [30.0, 10.0]}))
    assert with_c.loc["PAI 3 GHG intensity", "value"] == pytest.approx(without_c.loc["PAI 3 GHG intensity", "value"])
    assert with_c.loc["PAI 1 total", "value"] == pytest.approx(without_c.loc["PAI 1 total", "value"])
    assert with_c.loc["PAI 1 total", "coverage"].endswith("missing 60%")
