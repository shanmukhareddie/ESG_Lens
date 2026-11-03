import pandas as pd

from src.estimate.features import build
from src.validate.reconcile import candidates, identity_check, same_value


def frame(rows):
    return pd.DataFrame(rows, columns=["ticker", "metric", "year", "value_tco2e", "page", "quote"])


def test_same_value_allows_rounding_only():
    assert same_value(1_000_000, 1_004_000)
    assert not same_value(1_000_000, 1_100_000)
    assert same_value(0.4, 1.2)          # tiny values: one tonne either way


def test_candidates_status():
    rules = frame([("A", "ghg_scope1", 2025, 100, 1, "q"), ("A", "ghg_scope3", 2025, 900, 1, "q"),
                   ("A", "ghg_scope2_market", 2025, 50, 1, "q")])
    llm = frame([("A", "ghg_scope1", 2025, 100, 1, "q"), ("A", "ghg_scope3", 2025, 800, 1, "q"),
                 ("A", "ghg_scope2_location", 2025, 60, 1, "q")])
    status = candidates(rules, llm).set_index("metric")["status"]
    assert status["ghg_scope1"] == "agreed"
    assert status["ghg_scope3"] == "conflict"
    assert status["ghg_scope2_market"] == "rules_only"
    assert status["ghg_scope2_location"] == "llm_only"


def test_identity_check_flags_a_bad_total():
    df = frame([("A", "ghg_scope1", 2025, 10, 1, "q"), ("A", "ghg_scope2_market", 2025, 20, 1, "q"),
                ("A", "ghg_scope3", 2025, 70, 1, "q"), ("A", "ghg_total_market", 2025, 100, 1, "q"),
                ("B", "ghg_scope1", 2025, 10, 1, "q"), ("B", "ghg_scope2_market", 2025, 20, 1, "q"),
                ("B", "ghg_scope3", 2025, 70, 1, "q"), ("B", "ghg_total_market", 2025, 150, 1, "q"),
                ("C", "ghg_scope1", 2025, 10, 1, "q")])
    ok = identity_check(df)
    assert ok[df["ticker"] == "A"].all()
    assert not ok[df["ticker"] == "B"].any()
    assert ok[df["ticker"] == "C"].isna().all()


def test_features_one_row_per_company_year_with_gaps():
    companies = pd.DataFrame({"ticker": ["A", "B"], "sector": ["x", "y"], "subsector": ["x", "y"],
                              "country": ["FR", "FR"], "employees": [1000, None],
                              "revenue": [100.0, 1000.0], "market_cap": [10.0, 0.0]})
    emissions = frame([("A", "ghg_scope1", 2025, 5, 1, "q"), ("A", "ghg_scope1", 2024, 6, 1, "q")])
    df = build(companies, emissions).set_index(["ticker", "year"])
    assert len(df) == 4                                 # two companies, two years
    assert df.loc[("A", 2025), "ghg_scope1"] == 5
    assert df.loc[("A", 2024), "ghg_scope1"] == 6
    assert pd.isna(df.loc[("B", 2025), "ghg_scope1"])
    assert df.loc[("A", 2025), "log_employees"] == 3
    assert pd.isna(df.loc[("B", 2025), "log_market_cap"])      # a zero is not logged
    assert df.loc[("A", 2025), "n_reported"] == 1


def test_reviewer_decisions_and_added_rows_survive_a_rebuild(tmp_path, monkeypatch):
    from src.validate import reconcile

    monkeypatch.setattr(reconcile, "QUEUE", tmp_path / "queue.csv")
    rules = frame([("A", "ghg_scope1", 2025, 100, 1, "row a")])
    llm = frame([("A", "ghg_scope1", 2025, 900, 2, "row b")])
    df = candidates(rules, llm).assign(reason="extractors disagree", needs_review=True)
    queue = reconcile.review_queue(df)
    queue.loc[0, ["decision", "value_tco2e", "page", "quote"]] = ["manual", 150, 3, "row c"]
    extra = {"ticker": "A", "metric": "ghg_scope3", "year": 2025, "decision": "manual",
             "value_tco2e": 5000, "page": 4, "quote": "row d"}
    pd.concat([queue, pd.DataFrame([extra])]).to_csv(reconcile.QUEUE, index=False)

    queue = reconcile.review_queue(df)                    # rebuilt from scratch, decisions kept
    assert len(queue) == 2
    added = queue[queue["metric"] == "ghg_scope3"].iloc[0]
    assert added["reason"] == "added by reviewer"
    out = reconcile.accepted(df, queue, frame([])).set_index("metric")
    assert out.loc["ghg_scope1", "value_tco2e"] == 150 and out.loc["ghg_scope1", "quote"] == "row c"
    assert out.loc["ghg_scope3", "value_tco2e"] == 5000
