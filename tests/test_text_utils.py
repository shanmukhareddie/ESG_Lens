import pytest

from src.read.text_utils import dominant_unit_scale, normalize, parse_number, unit_scale


@pytest.mark.parametrize("token, decimal, expected", [
    ("78,371,616", ".", 78371616), ("1 234 567,5", ",", 1234567.5), ("698 274", ",", 698274),
    ("(1,234)", ".", -1234), ("2,087√", ".", 2087), ("1,234(1)", ".", 1234), ("45,8", ",", 45.8),
    ("1.3", ".", 1.3),
])
def test_parse_number(token, decimal, expected):
    assert parse_number(token, decimal) == pytest.approx(expected)


@pytest.mark.parametrize("token", ["-18%", "n/a", "Scope", "", "2025/2024"])
def test_parse_number_rejects(token):
    assert parse_number(token) is None


@pytest.mark.parametrize("text, scale", [
    ("(tCO2eq)", 1), ("ktCO2eq", 1e3), ("in thousands of tonnes of CO2e", 1e3), ("1,000 x tons of CO2e", 1e3),
    ("en milliers de tonnes", 1e3), ("Mt CO2 eq.", 1e6), ("million tons of CO2-eq", 1e6), ("t eqCO2", 1),
    ("Scope 1 GHG emissions", None),
])
def test_unit_scale(text, scale):
    assert unit_scale(text) == scale


def test_page_unit_is_the_most_mentioned_one():
    page = "Total in tCO2e ... (tCO2e) ... tCO2e. Revenue in millions of euros; 2 million tonnes of steel"
    assert dominant_unit_scale(page) == 1


def test_normalize_handles_accents_dashes_and_subscripts():
    assert normalize("Émissions tCO 2 e location‑based") == "emissions tco2 e location-based"


def test_dropped_subscript_unit_is_still_recognised():
    assert unit_scale("tCO e") == 1 and unit_scale("ktCO eq") == 1e3
    assert unit_scale("tons of CO e") is None     # too vague to trust


def test_layout_text_keeps_rows_and_marks_columns(report):
    import pymupdf

    from src.read.text_utils import layout_text
    with pymupdf.open(report) as doc:
        text = layout_text(doc[0])
    assert "Gross Scope 1 GHG emissions | 1,234 | 1,500 | -18%" in text
