import json

import pandas as pd

from src.read.targets_extract import evaluate, parse, pct_in_quote, score_page


def test_parse_keeps_valid_targets_and_reports_bad_ones():
    raw = json.dumps({"targets": [
        {"scope": "1+2", "base_year": 2020, "target_year": 2030, "reduction_pct": 46.3, "page": 3,
         "quote": "reduce absolute scope 1 and 2 GHG emissions by 46.3% by 2030 from a 2020 base year"},
        {"scope": "Scope 1 and 2", "base_year": 2020, "target_year": 2030, "reduction_pct": 46.3, "page": 3, "quote": "x"},
        {"scope": "3", "base_year": 2019, "target_year": 2020, "reduction_pct": 10, "page": 3, "quote": "x"},
    ]})
    records, errors = parse("BN", raw)
    assert [r.scope for r in records] == ["1+2"]
    assert len(errors) == 2                    # an unknown scope, and a target year already past


def test_parse_handles_broken_json():
    records, errors = parse("BN", "{not json")
    assert records == [] and errors


def test_percentage_must_be_in_the_quote():
    assert pct_in_quote(46.3, "by 46.3% by 2030")
    assert pct_in_quote(55, "Scopes 1 et 2 Absolu -55 % 2030")
    assert pct_in_quote(46.3, "réduire de 46,3 % d'ici 2030")
    assert not pct_in_quote(46, "by 46.3% by 2030")


def test_target_pages_score_higher_than_other_pages():
    target = "E1-4 targets: reduce absolute Scope 1 and 2 emissions by 46.3% by 2030 compared to the 2020 base year (SBTi)"
    other = "The Board of Directors met eight times in 2025. Attendance was 96%."
    assert score_page(target) > score_page(other) + 5


def test_evaluate_matches_on_scope_and_year():
    gold = pd.DataFrame({"ticker": ["A", "A", "A"], "scope": ["1+2", "3", "1+2+3"], "base_year": [2020] * 3,
                         "target_year": [2030, 2030, 2050], "reduction_pct": [46.3, 42.0, 90.0]})
    extracted = pd.DataFrame({"ticker": ["A", "A", "A"], "scope": ["1+2", "3", "1+2"], "base_year": [2020, 2019, 2020],
                              "target_year": [2030, 2030, 2040], "reduction_pct": [46.3, 30.0, 60.0],
                              "evidence_ok": [True, True, True]})
    out = evaluate(gold, extracted).set_index("scope")
    assert out.loc["1+2", "outcome"] == "correct" and out.loc["1+2", "base_year_ok"]
    assert out.loc["3", "outcome"] == "wrong_pct"
    assert out.loc["1+2+3", "outcome"] == "missed"


def test_site_builds_with_every_company_embedded():
    from src.report.build_site import build

    page = build()
    assert "__DATA__" not in page and "<!-- body -->" in page
    data = json.loads(page.split("const DATA = ", 1)[1].split(";\n", 1)[0])
    assert len(data["companies"]) == 40
    assert all(v["url"].startswith("http") for c in data["companies"] for v in c["values"])
