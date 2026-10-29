"""Climate metrics of an equity portfolio, from the cleaned emissions table.

    PAI 1  financed emissions   sum of  value_i / EVIC_i * emissions_i         tCO2e
    PAI 2  carbon footprint     PAI 1 (scopes 1+2+3) / value invested          tCO2e per EUR m invested
    PAI 3  GHG intensity        sum of  w_i * emissions_i / revenue_i          tCO2e per EUR m revenue
    WACI   (TCFD)               sum of  w_i * (scope 1 + 2)_i / revenue_i      tCO2e per EUR m revenue

PAI 1-3 are the first three principal adverse impact indicators of SFDR (Annex I).
EVIC = market cap + total debt + minority interest, with no cash deducted. Scope 2 is
market-based. The default portfolio is EUR 100m in the CAC 40, weighted by market cap.

A company's figure is the reported one for the year when there is one, else the one reported
for the year before, else the gap model's estimate (data/processed/estimates.csv: the median,
with P10 and P90 giving the low and high columns; adding P10s up assumes the estimates all err
in the same direction, so the range is wide on purpose). Holdings with no figure are left out:
PAI 1 is then a lower bound, and the ratios are computed on the holdings that are covered.
`coverage` says how much of the portfolio value each source accounts for.

Usage:
    python -m src.portfolio.metrics
    python -m src.portfolio.metrics --portfolio my_portfolio.csv     # columns: ticker, value_eur_m
"""

import argparse
from pathlib import Path

import pandas as pd

COMPANIES = Path("data/companies.csv")
EMISSIONS = Path("data/processed/emissions.csv")
ESTIMATES = Path("data/processed/estimates.csv")
YEAR = 2025
SCOPES = {"scope1": "ghg_scope1", "scope2": "ghg_scope2_market", "scope3": "ghg_scope3"}


def cap_weighted(companies: pd.DataFrame, total: float = 100.0) -> pd.DataFrame:
    w = companies.set_index("ticker")["market_cap"]
    return (w / w.sum() * total).rename("value_eur_m").reset_index()


def scope_values(emissions: pd.DataFrame, estimates: pd.DataFrame | None, year: int = YEAR) -> pd.DataFrame:
    """One row per company and scope: value, low, high (tCO2e) and where the figure comes from."""
    rows = []
    reported = emissions.set_index(["ticker", "metric", "year"])["value_tco2e"]
    est = estimates.set_index(["ticker", "metric", "year"]) if estimates is not None else None
    tickers = set(emissions["ticker"]) | (set(estimates["ticker"]) if estimates is not None else set())
    for ticker in sorted(tickers):
        for scope, metric in SCOPES.items():
            row = {"ticker": ticker, "scope": scope}
            if (ticker, metric, year) in reported.index:
                v = reported[(ticker, metric, year)]
                row.update(value=v, low=v, high=v, source="reported")
            elif (ticker, metric, year - 1) in reported.index:
                v = reported[(ticker, metric, year - 1)]
                row.update(value=v, low=v, high=v, source="reported_prior_year")
            elif est is not None and (ticker, metric, year) in est.index:
                e = est.loc[(ticker, metric, year)]
                row.update(value=e["p50"], low=e["p10"], high=e["p90"], source="estimated")
            else:
                continue
            rows.append(row)
    return pd.DataFrame(rows)


def holdings(portfolio: pd.DataFrame, companies: pd.DataFrame, scopes: pd.DataFrame) -> pd.DataFrame:
    """Portfolio joined to EVIC, revenue and each scope's value, wide: one row per holding."""
    c = companies.set_index("ticker")
    df = portfolio.set_index("ticker").join(c[["revenue"]])
    df["evic"] = c["market_cap"] + c["total_debt"].fillna(0) + c["minority_interest"].fillna(0)
    df["weight"] = df["value_eur_m"] / df["value_eur_m"].sum()
    wide = scopes.pivot(index="ticker", columns="scope", values=["value", "low", "high", "source"])
    wide.columns = [f"{scope}_{field}" for field, scope in wide.columns]
    return df.join(wide)


def _financed(h: pd.DataFrame, scopes: list[str], field: str) -> pd.Series:
    """Emissions attributed to the portfolio for each holding, NaN where a scope is missing."""
    emissions = sum(h[f"{s}_{field}"].astype(float) for s in scopes)
    return h["value_eur_m"] / h["evic"] * emissions


def _intensity(h: pd.DataFrame, scopes: list[str], field: str) -> float:
    per_revenue = sum(h[f"{s}_{field}"].astype(float) for s in scopes) / h["revenue"]
    covered = per_revenue.notna()
    return float((h.loc[covered, "weight"] * per_revenue[covered]).sum() / h.loc[covered, "weight"].sum())


def portfolio_metrics(h: pd.DataFrame) -> pd.DataFrame:
    rows = []
    all_scopes = list(SCOPES)
    for name, scopes in [("PAI 1 scope 1", ["scope1"]), ("PAI 1 scope 2", ["scope2"]),
                         ("PAI 1 scope 3", ["scope3"]), ("PAI 1 total", all_scopes)]:
        rows.append({"metric": name, "unit": "tCO2e",
                     **{f: float(_financed(h, scopes, f).sum()) for f in ("value", "low", "high")},
                     "coverage": coverage(h, scopes)})
    footprint = {}
    for f in ("value", "low", "high"):
        financed = _financed(h, all_scopes, f)
        covered = financed.notna()
        footprint[f] = float(financed[covered].sum() / h.loc[covered, "value_eur_m"].sum())
    rows.append({"metric": "PAI 2 carbon footprint", "unit": "tCO2e / EUR m invested", **footprint,
                 "coverage": coverage(h, all_scopes)})
    rows.append({"metric": "PAI 3 GHG intensity", "unit": "tCO2e / EUR m revenue",
                 **{f: _intensity(h, all_scopes, f) for f in ("value", "low", "high")},
                 "coverage": coverage(h, all_scopes)})
    rows.append({"metric": "WACI (scope 1+2)", "unit": "tCO2e / EUR m revenue",
                 **{f: _intensity(h, ["scope1", "scope2"], f) for f in ("value", "low", "high")},
                 "coverage": coverage(h, ["scope1", "scope2"])})
    return pd.DataFrame(rows)[["metric", "value", "low", "high", "unit", "coverage"]]


def coverage(h: pd.DataFrame, scopes: list[str]) -> str:
    """Share of portfolio value by data source. A holding counts as reported only if every
    scope needed is reported; one estimated scope makes it estimated."""
    sources = h[[f"{s}_source" for s in scopes]]
    kind = pd.Series("missing", index=h.index)
    complete = sources.notna().all(axis=1)
    kind[complete] = "estimated"
    kind[complete & sources.isin(["reported", "reported_prior_year"]).all(axis=1)] = "reported"
    share = h.groupby(kind)["weight"].sum()
    return ", ".join(f"{k} {share.get(k, 0):.0%}" for k in ("reported", "estimated", "missing"))


def contributions(h: pd.DataFrame) -> pd.DataFrame:
    """Each holding's share of the portfolio's financed emissions (scopes 1+2+3)."""
    financed = _financed(h, list(SCOPES), "value")
    out = pd.DataFrame({"weight": h["weight"], "financed_tco2e": financed,
                        "share_of_financed": financed / financed.sum()})
    return out.sort_values("financed_tco2e", ascending=False)


def load(portfolio_csv: Path | None = None) -> pd.DataFrame:
    companies = pd.read_csv(COMPANIES)
    portfolio = pd.read_csv(portfolio_csv) if portfolio_csv else cap_weighted(companies)
    estimates = pd.read_csv(ESTIMATES) if ESTIMATES.exists() else None
    return holdings(portfolio, companies, scope_values(pd.read_csv(EMISSIONS), estimates))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portfolio", type=Path)
    args = parser.parse_args()

    h = load(args.portfolio)
    pd.set_option("display.width", 160)
    pd.set_option("display.float_format", lambda x: f"{x:,.1f}")
    print(f"portfolio: EUR {h['value_eur_m'].sum():,.0f}m in {len(h)} companies, FY{YEAR} emissions\n")
    print(portfolio_metrics(h).to_string(index=False))
    print("\nlargest contributors to financed emissions:")
    print(contributions(h).head(8).to_string(formatters={"weight": "{:.1%}".format,
                                                         "share_of_financed": "{:.1%}".format}))


if __name__ == "__main__":
    main()
