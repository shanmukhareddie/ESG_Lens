"""Download sector, size and financials for each company from Yahoo Finance.

Writes data/companies.csv with the columns of the companies table, plus total debt and
minority interest from the year-end balance sheet (for EVIC). Money is in EUR millions;
`currency` is the currency of the company's own accounts (amounts in USD are converted at
that year's average rate).

Usage:
    python -m src.source.company_data
    python -m src.source.company_data --update total_debt minority_interest   # keep the other columns
"""

import argparse
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

SOURCES = Path("data/cac40_fy2025_sources.csv")
OUT = Path("data/companies.csv")
PAUSE = 2.0   # seconds between companies; Yahoo answers 429 to fast loops

# Pernod Ricard closes its year in June, and the project counts July 2025 - June 2026 as FY2025.
FISCAL_YEAR_END = {"RI": 2026}
# Yahoo has no profile for Michelin (ML.PA); these are the values it shows for the company elsewhere.
MISSING_PROFILE = {"ML": ("Consumer Cyclical", "Auto Parts", "France")}


def profile(ticker: yf.Ticker) -> dict:
    for attempt in range(3):
        try:
            info = ticker.info or {}
            if info.get("sector"):
                return info
        except Exception:
            pass
        time.sleep(PAUSE * (attempt + 2))
    return {}


def eur_rate(currency: str, year: int, cache: dict) -> float:
    """Average value in EUR of one unit of `currency` over `year`."""
    if currency == "EUR":
        return 1.0
    if (currency, year) not in cache:
        prices = yf.Ticker(f"EUR{currency}=X").history(start=f"{year}-01-01", end=f"{year + 1}-01-01")
        cache[(currency, year)] = float(1 / prices["Close"].mean())
    return cache[(currency, year)]


def statement_value(statement: pd.DataFrame | None, item: str, year: int) -> float | None:
    """One line of an annual statement for the fiscal year ending in `year`."""
    if statement is None or item not in statement.index:
        return None
    columns = [c for c in statement.columns if c.year == year]
    if not columns or pd.isna(statement.loc[item, columns[0]]):
        return None
    return float(statement.loc[item, columns[0]])


def market_cap(ticker: yf.Ticker, info: dict) -> float | None:
    if info.get("marketCap"):
        return info["marketCap"]
    try:   # when the profile is empty: last price x ordinary shares
        shares = ticker.balance_sheet.loc["Ordinary Shares Number"].dropna().iloc[0]
        return ticker.fast_info.get("lastPrice") * shares
    except Exception:
        return None


def fetch(ticker: str, yahoo_ticker: str, fx: dict) -> dict:
    t = yf.Ticker(yahoo_ticker)
    info = profile(t)
    sector, subsector, country = info.get("sector"), info.get("industry"), info.get("country")
    if not sector and ticker in MISSING_PROFILE:
        sector, subsector, country = MISSING_PROFILE[ticker]

    currency = info.get("financialCurrency") or "EUR"
    year = FISCAL_YEAR_END.get(ticker, 2025)
    revenue = statement_value(t.income_stmt, "Total Revenue", year)
    debt = statement_value(t.balance_sheet, "Total Debt", year)
    minority = statement_value(t.balance_sheet, "Minority Interest", year)
    mcap = market_cap(t, info)
    rate = eur_rate(currency, year, fx)
    return {
        "ticker": ticker,
        "sector": sector,
        "subsector": subsector,
        "employees": info.get("fullTimeEmployees"),
        "revenue": round(revenue * rate / 1e6, 1) if revenue else None,
        "revenue_year": year,
        "market_cap": round(mcap * eur_rate(info.get("currency") or "EUR", 2026, fx) / 1e6, 1) if mcap else None,
        "currency": currency,
        "country": country,
        "total_debt": round(debt * rate / 1e6, 1) if debt is not None else None,
        "minority_interest": round(minority * rate / 1e6, 1) if minority is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", nargs="+", help="refresh only these columns of companies.csv")
    args = parser.parse_args()

    fx: dict = {}
    rows = []
    for r in pd.read_csv(SOURCES).itertuples():
        rows.append(fetch(r.euronext_ticker, r.yahoo_ticker, fx))
        print(r.euronext_ticker, rows[-1]["sector"], flush=True)
        time.sleep(PAUSE)

    df = pd.DataFrame(rows)
    if args.update:
        old = pd.read_csv(OUT)
        df = old.drop(columns=args.update, errors="ignore").merge(df[["ticker", *args.update]], on="ticker", how="left")
    df["employees"] = df["employees"].astype("Int64")
    df.to_csv(OUT, index=False)
    print(f"saved {len(df)} companies to {OUT}")


if __name__ == "__main__":
    main()
