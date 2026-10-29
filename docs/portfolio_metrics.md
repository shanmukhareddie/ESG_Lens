# Portfolio climate metrics

What an investor holding the CAC 40 would report under SFDR, computed from the cleaned
emissions table (`python -m src.portfolio.metrics`, code in `src/portfolio/metrics.py`).

## Definitions

| Metric | Formula | Unit |
|---|---|---|
| PAI 1, financed emissions | Σ value_i / EVIC_i × emissions_i, per scope and in total | tCO2e |
| PAI 2, carbon footprint | PAI 1 (scopes 1+2+3) / value invested | tCO2e per €m invested |
| PAI 3, GHG intensity | Σ weight_i × emissions_i / revenue_i, scopes 1+2+3 | tCO2e per €m revenue |
| WACI (TCFD) | Σ weight_i × (scope 1 + 2)_i / revenue_i | tCO2e per €m revenue |

Choices, and why:
- **EVIC** = market cap + total debt + minority interest, with no cash deducted, as SFDR
  defines it. Debt and minority interest are the FY2025 balance-sheet values from Yahoo Finance.
  For banks this makes EVIC large: BNP Paribas' EVIC is about €499bn against a €94bn market cap,
  so an investor is attributed a small share of its emissions.
- **Scope 2 is market-based**, which reflects the electricity contracts a company has bought.
- **Missing values.** A figure reported for 2025 is used first, then the one reported for 2024,
  then the gap model's estimate. A holding with no figure is left out: PAI 1 then
  undercounts, and the ratios are computed over the holdings that are covered. Every metric
  states its coverage, because a footprint on 60% of a portfolio is not the same number.
- **Ranges.** Estimated values carry P10 and P90, which give the low and high columns. Adding
  the P10s of several companies assumes all estimates err in the same direction, so the range
  is wide on purpose.

## Results

€100m in the CAC 40, weighted by market cap, FY2025 emissions, before any estimates:

| Metric | Value | Coverage (share of portfolio value) |
|---|---|---|
| PAI 1 scope 1 | 6,144 tCO2e | reported 95% |
| PAI 1 scope 2 | 968 tCO2e | reported 95% |
| PAI 1 scope 3 | 52,171 tCO2e | reported 91% |
| PAI 1 total | 55,826 tCO2e | reported 91% |
| PAI 2 carbon footprint | 616 tCO2e / €m invested | reported 91% |
| PAI 3 GHG intensity | 1,328 tCO2e / €m revenue | reported 91% |
| WACI (scope 1+2) | 110 tCO2e / €m revenue | reported 93% |

The total is lower than the sum of the three scopes because it counts only holdings with all
three scopes. The 9% not covered are six companies whose values wait for review (Vinci, the
largest at 2.5% of the portfolio, is under review in full), plus ArcelorMittal and Eurofins,
which publish no Scope 3 table.

**Scope 3 changes the story.** It is 93% of financed emissions. Airbus (6.5% of the portfolio)
accounts for 35% of financed emissions, because its Scope 3 counts the fuel burnt by every
aircraft it sells over their lifetime (493 Mt), and TotalEnergies (7.8%) for another 22%.
WACI stops at Scope 2 and gives a different picture: Airbus falls to 0.5% of it, while Air
Liquide, whose own plants emit 34 Mt of Scope 1 and 2, is 59% of the WACI, ahead of
TotalEnergies at 21%. A portfolio manager who steers on WACI and one who steers on PAI 1
would sell different stocks.

Check by hand, Airbus: €6.46m held / €164,175m EVIC × 493,302,000 tCO2e = 19,420 tCO2e.

## Limits

- Market caps were fetched in October 2026, not at the fiscal year end that SFDR asks for.
- Pernod Ricard's fiscal year ends in June, so its "2025" covers July 2025 to June 2026.
- Scope 3 is the least comparable figure: companies choose which categories to count, and
  Saint-Gobain and Sanofi each print two different Scope 3 totals.
