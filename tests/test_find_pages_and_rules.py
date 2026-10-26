import pymupdf

from src.read.find_pages import rank_pages
from src.read.rules_extract import extract_page

from .conftest import ROWS, make_pdf


def test_ghg_table_page_ranks_first(report):
    assert rank_pages(report, n=2)[0][0] == 1


def _extract(path, decimal="."):
    with pymupdf.open(path) as doc:
        rows = extract_page(doc[0], 1, decimal)
    return {(r["metric"], r["year"]): r["value"] * r["scale"] for r in rows}


def test_rules_reads_each_metric_and_year(report):
    got = _extract(report)
    assert got[("ghg_scope1", 2025)] == 1234 and got[("ghg_scope1", 2024)] == 1500
    assert got[("ghg_scope2_market", 2025)] == 500
    assert got[("ghg_scope3", 2025)] == 10000            # the total, not category 1
    assert got[("ghg_total_market", 2024)] == 11100


def test_rules_maps_years_by_header_not_by_order(tmp_path):
    rows = [(label, [(330, cells[1][1]), (400, cells[0][1])]) for label, cells in ROWS]   # 2024 column first
    path = make_pdf(tmp_path / "REV_FY2025.pdf", [(330, "2024"), (400, "2025")], rows)
    got = _extract(path)
    assert got[("ghg_scope1", 2025)] == 1234 and got[("ghg_scope1", 2024)] == 1500


def test_rules_applies_unit_and_french_numbers(tmp_path):
    rows = [("Émissions brutes de GES scope 1", [(330, "698 274"), (400, "725 708")])]
    path = make_pdf(tmp_path / "FR_FY2025.pdf", [(330, "2025"), (400, "2024")], rows,
                    title="Émissions de GES (en milliers de tonnes)")
    assert _extract(path, decimal=",")[("ghg_scope1", 2025)] == 698_274_000
