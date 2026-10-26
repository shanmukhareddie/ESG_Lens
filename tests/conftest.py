"""Fake one-page reports, so the tests never need the real PDFs."""

import pymupdf
import pytest


def make_pdf(path, header, rows, title="Gross Scopes 1, 2, 3 and Total GHG emissions (E1-6) (tCO2e)", extra_pages=0):
    """A PDF whose page 1 holds a table laid out like an annual report: every cell is a
    separately placed piece of text, with no table structure in the file."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 80), title, fontsize=10)
    for x, text in header:
        page.insert_text((x, 120), text, fontsize=9)
    y = 142
    for label, cells in rows:
        page.insert_text((50, y), label, fontsize=9)
        for x, text in cells:
            page.insert_text((x, y), text, fontsize=9)
        y += 18
    for i in range(extra_pages):
        doc.new_page().insert_text((50, 80), f"Corporate governance report, page {i + 2}. Board of directors.", fontsize=10)
    doc.save(path)
    return path


ROWS = [
    ("Gross Scope 1 GHG emissions", [(330, "1,234"), (400, "1,500"), (470, "-18%")]),
    ("Gross location-based Scope 2 GHG emissions", [(330, "900"), (400, "950"), (470, "-5%")]),
    ("Gross market-based Scope 2 GHG emissions", [(330, "500"), (400, "600"), (470, "-17%")]),
    ("Total Gross indirect (Scope 3) GHG emissions", [(330, "10,000"), (400, "9,000"), (470, "+11%")]),
    ("1 Purchased goods and services", [(330, "6,000"), (400, "5,500"), (470, "+9%")]),
    ("Total GHG emissions (location-based)", [(330, "12,134"), (400, "11,450"), (470, "+6%")]),
    ("Total GHG emissions (market-based)", [(330, "11,734"), (400, "11,100"), (470, "+6%")]),
]


@pytest.fixture
def report(tmp_path):
    return make_pdf(tmp_path / "TEST_FY2025.pdf", [(330, "2025"), (400, "2024"), (460, "% change")], ROWS, extra_pages=3)
