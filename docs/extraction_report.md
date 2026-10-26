# Extracting GHG emissions from CAC 40 annual reports

## Goal

Turn the FY2025 sustainability statements of the CAC 40 into a table of emissions figures
that can be checked: every number keeps the page it came from and the exact row of text
it was read from. Two extractors are compared on the same hand-labelled answers: a
rule-based parser and an LLM (Groq).

## Data

- **Reports.** 40 companies, one report each (`data/cac40_fy2025_sources.csv`). 38 are full
  FY2025 reports with an ESRS sustainability statement. ArcelorMittal and Eurofins are
  Luxembourg issuers not yet under the CSRD; their sustainability reports have no ESRS E1-6
  table and are marked `partial`. Pernod Ricard's fiscal year ends in June, so its FY2025 is
  July 2025 to June 2026.
- **Gold labels.** 143 emissions values for 12 companies (`data/gold/gold_labels.csv`): Scope 1,
  Scope 2 location- and market-based, Scope 3 and both totals, for 2025 and 2024. Each label
  was read from the rendered page and stores the page and row text. For every company and
  year, Scope 1 + Scope 2 (market) + Scope 3 equals the reported total within 0.1%, which
  rules out transcription errors.
- **Gold targets.** 19 climate targets for 11 companies (`data/gold/gold_targets.csv`): scope,
  base year, target year and percentage cut. Only absolute targets on the company's own
  emissions are kept. BNP Paribas has none (its targets cover its lending and investment
  portfolios), so it does not appear.

## Method

1. **Page finder** (`src/read/find_pages.py`). Reports run to 300-1,000 pages and the
   emissions table sits on one or two. Each page is scored on simple signals (mentions of
   E1-6, of each scope, of both Scope 2 methods, a CO2e unit, a high density of large
   numbers). For all 12 gold companies the table is in the top 5 pages, and ranked first
   for 11 of them. Sending 5 pages instead of 500 is what keeps LLM cost and rate limits manageable.
2. **Taxonomy** (`src/read/taxonomy.yaml`). Six metrics mapped to ESRS E1-6, with the labels
   companies actually print (English and French) and the look-alike rows to reject, such as
   "percentage of Scope 1 from regulated schemes" or the 15 Scope 3 category rows.
3. **Rule-based extractor** (`src/read/rules_extract.py`). PDF tables carry no structure, so
   rows are rebuilt from word positions, labels are matched with the taxonomy, and each
   figure takes the year of the column header above it.
4. **LLM extractor** (`src/read/llm_extract.py`).
5. **Evidence checks** (`src/validate/evidence.py`). A value is kept only if its page exists,
   every word of its quote is printed on that page, the value appears in the quote and its
   unit converts to tonnes of CO2e. All 143 gold labels pass these checks.

## Results


## What made it hard

- **Layouts differ more than the standard suggests.** ESRS fixes what to disclose, not how.
  Orange prints one "2025" heading over eight business-segment columns, so the group total
  has no year directly above it. Michelin prints figures on the last line of a three-line
  label. Bouygues has a column per subsidiary before the group column.
- **Units hide far from the figures.** Bureau Veritas writes "1,000 x tons of CO2e" inside the
  row label; Danone puts "(in kt CO2e)" in a table caption; Stellantis reports in million
  tonnes with one decimal. A wrong unit is a 1,000x error, so unit detection matters as much
  as reading the number.
- **The same figure has several "right" answers.** Sanofi prints a gross and a market-based
  Scope 1, TotalEnergies reports an ESRS perimeter and an operated perimeter, Veolia shows
  Scope 3 with and without voluntary categories, Pernod Ricard restated its 2024 figures in
  the 2025 report. The gold set records which one was chosen and why in its notes.
- **Look-alike rows.** "Scope 1 & 3 FLAG", "fuel-related activities not included in Scope 1
  or Scope 2" and Scope 3 category rows all contain the words a naive search looks for.

## Next

- Estimate the missing values (Eurofins Scope 3, partial disclosures) with a model that
  returns a range rather than one number.
- Compute investor metrics on the cleaned data: WACI and PAI 1-3.
