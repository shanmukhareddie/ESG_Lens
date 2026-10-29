"""One row per company and year: what we know about it (sector, size) and its reported emissions.

The emission columns are the targets of the gap-filling model; an empty cell is a gap.
Size is logged because emissions and company size both span several orders of magnitude.

Usage:
    from src.estimate.features import load; df = load()
    python -m src.estimate.features        # how many values each metric has
"""

from pathlib import Path

import numpy as np
import pandas as pd

COMPANIES = Path("data/companies.csv")
EMISSIONS = Path("data/processed/emissions.csv")
YEARS = (2024, 2025)
METRICS = ["ghg_scope1", "ghg_scope2_location", "ghg_scope2_market",
           "ghg_scope3", "ghg_total_location", "ghg_total_market"]


def build(companies: pd.DataFrame, emissions: pd.DataFrame, years=YEARS) -> pd.DataFrame:
    """Size is the latest known (revenue_year), used for both years: it moves far less than emissions."""
    df = companies[["ticker", "sector", "subsector", "country", "employees", "revenue", "market_cap"]].copy()
    for col in ("employees", "revenue", "market_cap"):
        df[f"log_{col}"] = np.log10(df[col].where(df[col] > 0))
    df = df.merge(pd.DataFrame({"year": list(years)}), how="cross")

    reported = (emissions[emissions["year"].isin(years)]
                .pivot_table(index=["ticker", "year"], columns="metric", values="value_tco2e")
                .reindex(columns=METRICS))
    df = df.merge(reported, left_on=["ticker", "year"], right_index=True, how="left")
    df["n_reported"] = df[METRICS].notna().sum(axis=1)
    return df


def load() -> pd.DataFrame:
    return build(pd.read_csv(COMPANIES), pd.read_csv(EMISSIONS))


def main() -> None:
    df = load()
    print(f"{len(df)} company-years for {df['ticker'].nunique()} companies")
    print("values reported per metric:")
    print(df[METRICS].notna().sum().to_string())


if __name__ == "__main__":
    main()
