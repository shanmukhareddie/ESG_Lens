"""Integrity of the committed gold sets and source list."""

import pandas as pd

SOURCES = pd.read_csv("data/sources.csv")
GOLD = pd.read_csv("data/gold/gold_labels.csv")
TARGETS = pd.read_csv("data/gold/gold_targets.csv")
# Hermès builds its market-based total from its own "including contractual instruments" Scope 1
# and 3, not from the gross figures (see the note on those labels).
TOTAL_NOT_SUM = {("RMS", 2024), ("RMS", 2025)}


def test_sources_one_row_per_company():
    cac40 = SOURCES[SOURCES.in_cac40]
    assert len(cac40) == 40 and cac40["isin"].is_unique
    assert SOURCES.euronext_ticker.is_unique
    assert set(SOURCES.doc_status) <= {"ok", "partial"}


def test_gold_labels_unique_and_add_up():
    assert not GOLD.duplicated(["ticker", "metric", "year"]).any()
    assert set(GOLD.ticker) <= set(SOURCES.euronext_ticker)
    p = GOLD.pivot_table(index=["ticker", "year"], columns="metric", values="value_tco2e")
    p = p[~p.index.isin(TOTAL_NOT_SUM)]
    resid = (p.ghg_scope1 + p.ghg_scope2_market + p.ghg_scope3) / p.ghg_total_market - 1
    assert resid.abs().max() < 0.001          # Scope 1 + 2 + 3 = total within 0.1 %


def test_each_company_is_in_one_split():
    assert set(GOLD.split) == {"dev", "test1", "test2"}
    assert GOLD.groupby("ticker")["split"].nunique().max() == 1
    assert GOLD.groupby("split")["ticker"].nunique().to_dict() == {"dev": 12, "test1": 4, "test2": 4}


def test_gold_targets_complete_and_sane():
    assert not TARGETS.isna().any().any()
    assert (TARGETS.target_year > TARGETS.base_year).all()
    assert TARGETS.reduction_pct.between(0, 100).all()
    assert set(TARGETS.scope) <= {"1+2", "3", "1+3", "1+2+3"}
