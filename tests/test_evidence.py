import pandas as pd
import pytest

from src.validate import evidence


@pytest.mark.parametrize("value, text, ok", [
    (21516, "Scope 1 Gross GHG Emissions 21,516 23,587", True),
    (698274, "scope 1 (t eqCO2) 698 274 725 708", True),
    (1.3, "Gross Scope 1 GHG Emissions 1.3 1.1", True),
    (1516, "Scope 1 21,516", False),           # a partial match is not a match
])
def test_value_in_quote(value, text, ok):
    assert evidence.value_in_quote(value, text) is ok


def test_quote_must_be_on_the_page():
    page = "Scope 1 Gross GHG Emissions (tCO\n2\ne)\n21,516\n23,587"
    assert evidence.quote_on_page("Scope 1 Gross GHG Emissions (tCO 2 e) 21,516 23,587", page)
    assert not evidence.quote_on_page("Scope 1 Gross GHG Emissions 99,999", page)


def test_check_flags_each_failure(monkeypatch):
    monkeypatch.setattr(evidence, "page_text", lambda t, p: "Gross Scope 1 GHG emissions ktCO2eq 480 462" if p == 1 else None)
    recs = pd.DataFrame([
        {"ticker": "X", "metric": "ghg_scope1", "year": 2025, "value": 480, "unit_as_printed": "ktCO2eq", "page": 1,
         "quote": "Gross Scope 1 GHG emissions ktCO2eq 480 462"},
        {"ticker": "X", "metric": "ghg_scope1", "year": 2025, "value": 480, "unit_as_printed": "ktCO2eq", "page": 9,
         "quote": "Gross Scope 1 GHG emissions ktCO2eq 480 462"},     # page does not exist
        {"ticker": "X", "metric": "ghg_scope1", "year": 2025, "value": 481, "unit_as_printed": "", "page": 1,
         "quote": "Gross Scope 1 GHG emissions ktCO2eq 480 462"},     # value not in quote, no unit
    ])
    out = evidence.check(recs)
    assert out.evidence_ok.tolist() == [True, False, False]
    assert out.value_tco2e[0] == 480_000
    assert not out.value_in_quote[2] and not out.unit_ok[2]
