"""Download sector, size and financials for each company from Yahoo Finance.

Writes data/companies.csv with the columns of the companies table. Revenue and
market cap are in EUR millions; `currency` is the currency of the company's own
accounts (revenue in USD is converted at that year's average rate).

Usage:
    python -m src.source.company_data
"""

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


def annual_revenue(ticker: yf.Ticker, year: int) -> float | None:
    income = ticker.income_stmt
    if income is None or "Total Revenue" not in income.index:
        return None
    columns = [c for c in income.columns if c.year == year]
    if not columns or pd.isna(income.loc["Total Revenue", columns[0]]):
        return None
    return float(income.loc["Total Revenue", columns[0]])


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
    revenue = annual_revenue(t, year)
    mcap = market_cap(t, info)
    return {
        "ticker": ticker,
        "sector": sector,
        "subsector": subsector,
        "employees": info.get("fullTimeEmployees"),
        "revenue": round(revenue * eur_rate(currency, year, fx) / 1e6, 1) if revenue else None,
        "revenue_year": year,
        "market_cap": round(mcap * eur_rate(info.get("currency") or "EUR", 2026, fx) / 1e6, 1) if mcap else None,
        "currency": currency,
        "country": country,
    }


def main() -> None:
    fx: dict = {}
    rows = []
    for r in pd.read_csv(SOURCES).itertuples():
        rows.append(fetch(r.euronext_ticker, r.yahoo_ticker, fx))
        print(r.euronext_ticker, rows[-1]["sector"], flush=True)
        time.sleep(PAUSE)

    df = pd.DataFrame(rows)
    df["employees"] = df["employees"].astype("Int64")
    df.to_csv(OUT, index=False)
    print(f"saved {len(df)} companies to {OUT}")


if __name__ == "__main__":
    main()
