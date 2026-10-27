import json

import pandas as pd
import pytest
from pydantic import ValidationError

from src.read.llm_extract import compact, parse
from src.read.schema import EmissionRecord
from src.validate.evaluate import classify, evaluate, summarize, tolerance

GOOD = {"ticker": "BN", "metric": "ghg_scope1", "year": 2025, "value": 697267,
        "unit_as_printed": "t CO2e", "page": 227, "quote": "Gross scope 1 GHG emissions 697,267"}


def test_valid_record():
    assert EmissionRecord(**GOOD).value == 697267


@pytest.mark.parametrize("field, bad", [
    ("metric", "scope_1"), ("year", 2019), ("value", -5), ("page", 0), ("quote", ""), ("unit_as_printed", "  "),
])
def test_invalid_records_are_rejected(field, bad):
    with pytest.raises(ValidationError):
        EmissionRecord(**{**GOOD, field: bad})


def test_parse_keeps_valid_records_and_reports_bad_ones():
    good = {k: v for k, v in GOOD.items() if k != "ticker"}
    raw = json.dumps({"records": [good, {"metric": "ghg_scope9", "year": 2025}]})
    records, errors = parse("BN", raw)
    assert len(records) == 1 and len(errors) == 1
    assert parse("BN", "not json")[1]


def test_compact_keeps_table_lines_only():
    page = "Gross Scope 1 GHG emissions\n697,267\n" + "Our long term ambition is to protect the planet " * 5
    assert compact(page) == "Gross Scope 1 GHG emissions\n697,267"


@pytest.mark.parametrize("pred, outcome", [
    (1000.0, "correct"), (1004.0, "correct"), (1200.0, "wrong_year"), (1.0, "wrong_unit"),
    (777.0, "wrong_value"), (float("nan"), "missed"),
])
def test_classify(pred, outcome):
    assert classify(pred, 1000.0, 1200.0, tolerance(1000.0, "tCO2e")) == outcome


def test_tolerance_follows_printed_precision():
    assert tolerance(1_300_000, "million tons of CO2-eq") == 50_000
    assert tolerance(71_000, "1000 x tons CO2e") == 500
    assert tolerance(21_516, "tCO2e") == pytest.approx(107.58)


def test_evaluate_and_summarize():
    gold = pd.DataFrame([
        {"ticker": "A", "metric": "ghg_scope1", "year": 2025, "value_tco2e": 100, "unit_as_printed": "t", "pdf_page": 1},
        {"ticker": "A", "metric": "ghg_scope1", "year": 2024, "value_tco2e": 120, "unit_as_printed": "t", "pdf_page": 1},
    ])
    preds = pd.DataFrame([{"ticker": "A", "metric": "ghg_scope1", "year": 2025, "value_tco2e": 120}])
    res = evaluate(gold, preds)
    assert sorted(res["outcome"]) == ["missed", "wrong_year"]
    s = summarize(res.assign(extractor="x"), ["extractor"]).iloc[0]
    assert s["precision"] == 0 and s["recall"] == 0
