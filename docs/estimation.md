# Estimating missing emissions

`src/estimate/model.py` estimates the emissions a company does not report, as a range, so the
portfolio metrics can cover every holding. Estimates are stored apart from reported figures
(`data/processed/estimates.csv`, source `estimated` in Supabase) and never replace one.

## What is missing

After the review, every company reports Scope 1 and Scope 2 for 2025. Two report no full
Scope 3 in either year: ArcelorMittal (its sustainability report gives only a "limited"
steel-industry Scope 3) and Eurofins (no Scope 3 table). Those are the gaps the model fills.
A company that reports a metric for the other year is not estimated: emissions change about
5% a year, so last year's figure beats any model, and the portfolio metrics use it.

## Method

- **Target:** log10 of tCO2e. Emissions range over five orders of magnitude, and on a log
  scale an error of 0.3 means a factor of 2 for a small company and a large one alike.
- **Features:** log revenue, log employees (Yahoo has no count for Michelin, so it comes from
  Michelin's report; a company without one would get its sector's median and a flag), and
  sector as one-hot columns. Market cap is left out (r < 0.25 with
  every scope), subsector too (about one company per level). For Scope 3 the company's own
  reported Scope 1 + 2 is added.
- **Models:** the sector's median emissions per euro of revenue (the baseline to beat); ridge
  regression; and gradient boosting with quantile loss for P10, P50 and P90. Ridge's range comes
  from the 10th and 90th percentiles of its own out-of-fold errors on the training rows.
- **Validation:** rows are company-years, and a company's two years are near copies, so every
  split keeps both years of a company together (GroupKFold on ticker, 5 folds). Ridge's alpha
  is also chosen by grouped inner cross-validation; leave-one-out would keep the other year in
  training and pick too little regularisation.

## Results

Out-of-fold, on every company-year that reports the metric:

| Scope | Model | Error (log10) | Within 2× | P10-P90 coverage | P90 / P10 |
|---|---|---|---|---|---|
| Scope 1 (79 rows) | Sector median | 0.72 | 22% | | |
| | Ridge | **0.71** | 27% | 84% | 383× |
| | Gradient boosting | 0.82 | 20% | 56% | 43× |
| Scope 2 market (80) | Sector median | **0.70** | 25% | | |
| | Ridge | 0.70 | 29% | 84% | 387× |
| | Gradient boosting | 0.71 | 35% | 59% | 31× |
| Scope 3 (76) | Sector median | 0.55 | 25% | | |
| | Ridge, size and sector | 0.53 | 26% | 87% | 60× |
| | Ridge, plus own Scope 1 + 2 | **0.41** | 46% | 84% | 46× |
| | Gradient boosting, plus own Scope 1 + 2 | 0.57 | 34% | 59% | 13× |

- **Size and sector explain little.** For Scope 1 and 2 the best model is barely better than,
  or level with, the sector median, with a typical error of a factor of 5. Companies of the same size and
  sector run very different assets: Airbus and Vinci are both Industrials with about €75bn of
  revenue, and Vinci's Scope 1 (2.0 Mt) is four times Airbus's (0.48 Mt).
- **Ridge knows what it does not know; gradient boosting does not.** Ridge's P10-P90 range holds
  the true value 84-87% of the time, close to the 80% it promises. Gradient boosting's ranges
  are narrower and miss 40% of the time: with about 70 rows its quantiles overfit.
- **A company's own Scope 1 + 2 is the best predictor of its Scope 3.** It cuts the error from a
  factor of 3.4 to 2.6 and nearly doubles the share within a factor of 2.

Ridge makes the estimates.

## Estimates

| Company | Scope 3, 2025, P50 | P10 to P90 |
|---|---|---|
| ArcelorMittal | 80 Mt | 21 to 433 Mt |
| Eurofins | 0.63 Mt | 0.16 to 3.4 Mt |

A check on ArcelorMittal: its report discloses two Scope 3 categories, purchased materials
(19.4 Mt) and fuel and energy (11.4 Mt), so the full Scope 3 is at least 31 Mt. The P50 is well
above that floor; the P10 is below it, which shows how wide the range has to be.

In the portfolio these estimates are 2% of the value invested. They move PAI 1 from 63,700 to
76,600 tCO2e between P10 and P90 (see `docs/portfolio_metrics.md`).

## Limits

- 40 companies is a small training set, and some sectors have a single company.
- Size is the latest revenue and headcount, used for both years.
- The model learns the CAC 40's own reporting choices, including which Scope 3 categories each
  company counts.
