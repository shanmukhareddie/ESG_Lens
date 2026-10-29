"""Load the climate targets into Supabase, creating the targets table if it does not exist.

Rows are upserted on (company_id, scope, target_year); with --replace, targets no longer in
the file are deleted.

Usage:
    python -m src.load.targets_to_supabase
    python -m src.load.targets_to_supabase --replace
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.load.to_supabase import SOURCES, company_ids, connect

SCHEMA = Path("src/targets_schema.sql")
TARGETS = Path("data/processed/targets.csv")

UPSERT_TARGET = """
    INSERT INTO targets (company_id, scope, base_year, target_year, reduction_pct, source,
                         page_number, quoted_sentence, pdf_url, loaded_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (company_id, scope, target_year) DO UPDATE SET
        base_year = EXCLUDED.base_year, reduction_pct = EXCLUDED.reduction_pct, source = EXCLUDED.source,
        page_number = EXCLUDED.page_number, quoted_sentence = EXCLUDED.quoted_sentence,
        pdf_url = EXCLUDED.pdf_url, loaded_at = EXCLUDED.loaded_at
"""
DELETE_STALE = """
    DELETE FROM targets t
    WHERE (t.company_id, t.scope, t.target_year) NOT IN (
        SELECT * FROM unnest(%s::int[], %s::text[], %s::int[]))
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace", action="store_true", help="delete targets that are no longer in the file")
    args = parser.parse_args()

    df = pd.read_csv(TARGETS, dtype={"scope": str})
    urls = pd.read_csv(SOURCES).set_index("euronext_ticker")["fy2025_link"]
    now = datetime.now(UTC).replace(tzinfo=None)

    with connect() as con:   # a single transaction: either every row is written or none
        con.execute(SCHEMA.read_text())
        ids = company_ids(con)
        rows = [
            (ids[r.ticker], r.scope, None if pd.isna(r.base_year) else int(r.base_year), int(r.target_year),
             float(r.reduction_pct), r.source, int(r.page), r.quote, urls[r.ticker], now)
            for r in df.itertuples()
        ]
        with con.cursor() as cur:
            cur.executemany(UPSERT_TARGET, rows)
            if args.replace:
                keys = list(zip(*[(r[0], r[1], r[3]) for r in rows])) or [[], [], []]
                cur.execute(DELETE_STALE, tuple(map(list, keys)))
                print(f"deleted {cur.rowcount} targets no longer in {TARGETS}")
        total = con.execute("SELECT count(*) FROM targets").fetchone()[0]
    print(f"upserted {len(rows)} targets from {TARGETS}; rows in database: {total}")


if __name__ == "__main__":
    main()
