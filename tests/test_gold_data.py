"""Integrity of the committed gold sets and source list."""

import pandas as pd

SOURCES = pd.read_csv("data/cac40_fy2025_sources.csv")
GOLD = pd.read_csv("data/gold/gold_labels.csv")
TARGETS = pd.read_csv("data/gold/gold_targets.csv")


def test_sources_one_row_per_company():
    assert len(SOURCES) == 40 and SOURCES.euronext_ticker.is_unique and SOURCES["isin"].is_unique
    assert set(SOURCES.doc_status) <= {"ok", "partial"}


def test_gold_labels_unique_and_add_up():
    assert not GOLD.duplicated(["ticker", "metric", "year"]).any()
    assert set(GOLD.ticker) <= set(SOURCES.euronext_ticker)
    p = GOLD.pivot_table(index=["ticker", "year"], columns="metric", values="value_tco2e")
    resid = (p.ghg_scope1 + p.ghg_scope2_market + p.ghg_scope3) / p.ghg_total_market - 1
    assert resid.abs().max() < 0.001          # Scope 1 + 2 + 3 = total within 0.1 %


def test_gold_targets_complete_and_sane():
    assert not TARGETS.isna().any().any()
    assert (TARGETS.target_year > TARGETS.base_year).all()
    assert TARGETS.reduction_pct.between(0, 100).all()
    assert set(TARGETS.scope) <= {"1+2", "3", "1+3", "1+2+3"}
