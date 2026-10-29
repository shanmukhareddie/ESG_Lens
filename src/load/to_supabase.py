"""Load companies and emissions into the Supabase database.

Rows are upserted, so a second run updates rows instead of duplicating them:
companies are matched on isin, metrics on (company_id, metric_name, year).

Usage:
    python -m src.load.to_supabase companies
    python -m src.load.to_supabase metrics data/gold/gold_labels.csv
    python -m src.load.to_supabase metrics data/processed/emissions.csv

A metrics file needs ticker, metric, year, value_tco2e, page and quote (pdf_page and
row_text are accepted too). Rows that failed the evidence checks are not loaded.
With --replace, rows of the same source that are no longer in the file are deleted, so a
value sent back to review leaves the database too.
"""

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

SOURCES = Path("data/cac40_fy2025_sources.csv")
COMPANIES = Path("data/companies.csv")

UPSERT_COMPANY = """
    INSERT INTO companies (isin, name, sector, subsector, employees, revenue, revenue_year, market_cap, currency, country)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (isin) DO UPDATE SET
        name = EXCLUDED.name, sector = EXCLUDED.sector, subsector = EXCLUDED.subsector,
        employees = EXCLUDED.employees, revenue = EXCLUDED.revenue, revenue_year = EXCLUDED.revenue_year,
        market_cap = EXCLUDED.market_cap, currency = EXCLUDED.currency, country = EXCLUDED.country
"""

UPSERT_METRIC = """
    INSERT INTO metrics (company_id, metric_name, year, value, unit, source, page_number,
                         quoted_sentence, pdf_url, extracted_at)
    VALUES (%s, %s, %s, %s, 'tCO2e', %s, %s, %s, %s, %s)
    ON CONFLICT (company_id, metric_name, year) DO UPDATE SET
        value = EXCLUDED.value, unit = EXCLUDED.unit, source = EXCLUDED.source,
        page_number = EXCLUDED.page_number, quoted_sentence = EXCLUDED.quoted_sentence,
        pdf_url = EXCLUDED.pdf_url, extracted_at = EXCLUDED.extracted_at
"""


DELETE_STALE = """
    DELETE FROM metrics m
    WHERE m.source = %s
      AND (m.company_id, m.metric_name, m.year) NOT IN (
          SELECT * FROM unnest(%s::int[], %s::text[], %s::int[]))
"""


def connect() -> psycopg.Connection:
    load_dotenv()
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=20)


def clean(value):
    return None if pd.isna(value) else value


def load_companies(con: psycopg.Connection) -> int:
    sources = pd.read_csv(SOURCES)[["euronext_ticker", "isin", "company_full_name"]]
    companies = pd.read_csv(COMPANIES).merge(sources, left_on="ticker", right_on="euronext_ticker")
    rows = [
        (r.isin, r.company_full_name, clean(r.sector), clean(r.subsector),
         None if pd.isna(r.employees) else int(r.employees), clean(r.revenue), int(r.revenue_year),
         clean(r.market_cap), clean(r.currency), clean(r.country))
        for r in companies.itertuples()
    ]
    with con.cursor() as cur:
        cur.executemany(UPSERT_COMPANY, rows)
    return len(rows)


def company_ids(con: psycopg.Connection) -> dict[str, int]:
    """Euronext ticker -> company_id, joined through the ISIN."""
    id_by_isin = dict(con.execute("SELECT isin, company_id FROM companies").fetchall())
    sources = pd.read_csv(SOURCES)
    return {t: id_by_isin[i] for t, i in zip(sources["euronext_ticker"], sources["isin"]) if i in id_by_isin}


def load_metrics(con: psycopg.Connection, csv: Path, source: str = "reported",
                 replace: bool = False) -> tuple[int, int, int]:
    df = pd.read_csv(csv).rename(columns={"pdf_page": "page", "row_text": "quote"})
    skipped = 0
    if "evidence_ok" in df:
        passed = df["evidence_ok"].astype(bool)
        skipped = int((~passed).sum())
        df = df[passed]
    df = df.dropna(subset=["value_tco2e"])

    ids = company_ids(con)
    urls = pd.read_csv(SOURCES).set_index("euronext_ticker")["fy2025_link"]
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = [
        (ids[r.ticker], r.metric, int(r.year), float(r.value_tco2e), source, int(r.page), r.quote, urls[r.ticker], now)
        for r in df.itertuples()
    ]
    deleted = 0
    with con.cursor() as cur:
        cur.executemany(UPSERT_METRIC, rows)
        if replace:
            keys = list(zip(*[(r[0], r[1], r[2]) for r in rows])) or [[], [], []]
            cur.execute(DELETE_STALE, (source, *map(list, keys)))
            deleted = cur.rowcount
    return len(rows), skipped, deleted


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="table", required=True)
    sub.add_parser("companies")
    metrics = sub.add_parser("metrics")
    metrics.add_argument("csv", type=Path)
    metrics.add_argument("--source", default="reported", choices=["reported", "estimated"])
    metrics.add_argument("--replace", action="store_true", help="delete rows of this source not in the file")
    args = parser.parse_args()

    with connect() as con:   # a single transaction: either every row is written or none
        if args.table == "companies":
            print(f"upserted {load_companies(con)} companies")
        else:
            n, skipped, deleted = load_metrics(con, args.csv, args.source, args.replace)
            print(f"upserted {n} metrics from {args.csv}" + (f", skipped {skipped} that failed checks" if skipped else "")
                  + (f", deleted {deleted} no longer in the file" if args.replace else ""))
        totals = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("companies", "metrics")}
        print(f"rows in database: {totals}")


if __name__ == "__main__":
    main()
