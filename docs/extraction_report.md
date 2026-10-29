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
- **Test labels.** 46 values for 4 companies that were not looked at while building either
  extractor (`data/gold/test_labels.csv`): Schneider Electric, Saint-Gobain, Kering (in French)
  and SNCF, a state-owned group outside the CAC 40 (`data/test_sources.csv`). Saint-Gobain does
  not print its 2024 totals, so it has 10 values. Every total equals Scope 1 + 2 + 3.

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
4. **LLM extractor** (`src/read/llm_extract.py`). `openai/gpt-oss-120b` on Groq, temperature 0,
   JSON output validated against a pydantic schema (`src/read/schema.py`), one retry with the
   validation errors when a reply is invalid, every reply cached. The free tier allows 8,000
   tokens per minute, so each page is cut down to its table lines and the prompt is capped at
   about 4,000 tokens.
5. **Evidence checks** (`src/validate/evidence.py`). A value is kept only if its page exists,
   every word of its quote is printed on that page, the value appears in the quote and its
   unit converts to tonnes of CO2e. All 143 gold labels pass these checks.

## Results

Scored on the 143 gold values (`python -m src.validate.evaluate`). A value is correct when it is
within 0.5% of the gold value or within the rounding of the printed unit.

| Extractor | Correct | Precision | Recall | Missed | Wrong year | Wrong value |
|---|---|---|---|---|---|---|
| Rules | 122 | 91.7% | 85.3% | 10 | 0 | 11 |
| LLM v1, plain page text | 108 | 81.8% | 75.5% | 11 | 5 | 19 |
| LLM v2, layout-preserving text | 111 | 87.4% | 77.6% | 16 | 0 | 16 |

**v1 to v2.** The first LLM run read the plain PDF text, where every table cell sits on its own
line. It could not tell which figure belonged to which year and picked AXA's 2019 base-year
column as 2025. v2 sends each table row on one line with ` | ` between columns, which removed
every wrong-year error. A second fix was in my own code, not the model: BNP Paribas prints the
unit as "tCO2e" with the subscript stored separately, the model copied it as "tCO e" and the unit
parser rejected all 12 values (v1 scored 96 before that fix). Both changes were made after
looking at errors on this same gold set, so these are development scores (see the test set below).

**The LLM is not fully repeatable.** The first v2 run scored 117. When four gold companies were
sent again with the identical request, at temperature 0, BNP Paribas came back with 2024 only:
six values lost, 111 in the table above. Every reply is now cached, so the figures above can be
reproduced from the cache, but a fresh run can differ by a few values.

**Where both still fail.**
- *Orange*: one "2025" heading spans eight business-segment columns, and both extractors read a
  segment (France) instead of the group total.
- *Sanofi*: two rows are called "total indirect Scope 3"; both extractors take the narrower
  transition-plan figure (3,436 kt) instead of the ESRS total (4,112 kt).
- *L'Oréal* (LLM only): the year headers wrap onto two lines ("2019 comparativ / e figures"),
  and the model reads the 2019 column as 2025.
- *TotalEnergies* (LLM only): returns Scopes 1 and 2 but no Scope 3 or totals, on the densest page of the set.

The rules parser is more precise because it measures where each figure sits on the page; the LLM
reads only text. The LLM needed no layout code and generalises to labels the taxonomy has never
seen, so the two are best used together: accept a value when they agree, and send the
disagreements to a person.

## Held-out test

Scored on the 46 test values (`python -m src.validate.evaluate --gold data/gold/test_labels.csv ...`).
Nothing was changed after seeing these results.

| Extractor | Correct | Precision | Recall | Missed | Wrong unit | Wrong value |
|---|---|---|---|---|---|---|
| Rules | 28 | 70.0% | 60.9% | 6 | 4 | 8 |
| LLM v2 | 36 | 100% | 78.3% | 10 | 0 | 0 |

The ranking flips. On the development set the rules were more precise; on new companies they
drop from 92% to 70% precision, while the LLM makes no wrong value at all. The rules were
partly fitted to the twelve layouts they were built on, which is exactly what a test set is for.

- *Schneider Electric*: both extractors get all 12 values.
- *Saint-Gobain*: the rules get all 10, including Scope 3, where the ESRS table labels the SBTi
  perimeter (23.4 Mt) as "total Scope 3" but the reported totals only add up with the group
  figure (78.4 Mt). The LLM read Scopes 1 to 3 correctly, but all its values were rejected by the
  evidence check because the unit is printed as a bare "t", which the unit parser does not accept.
  It also took the SBTi totals instead of the group totals.
- *Kering*: French thousands are separated by spaces, and the rules read "1 965 802" as 1,965:
  a parser bug on figures with three groups. The LLM gets all 12.
- *SNCF*: the rules take figures from the wrong table and miss the totals. The LLM gets all 12.

**After fixing both bugs.** Both were fixed afterwards, because the same two bugs also caused
review work in the main table (Eiffage and Unibail print three-group figures). Re-scored on the
same 46 values, which are no longer held out since the fixes were made after seeing them:

| Extractor | Correct | Precision | Recall |
|---|---|---|---|
| Rules | 32 | 80.0% | 69.6% |
| LLM v2 | 44 | 95.7% | 95.7% |

The LLM's two errors are Saint-Gobain's SBTi totals. The development scores did not change:
none of the twelve gold companies prints a three-group figure or a bare "t". The table above
it remains the honest test score; a new held-out set would be needed to measure the fixed
version.

## Combining the two

`src/validate/reconcile.py` merges both extractors into one table (`data/processed/emissions.csv`).
Measured on the gold companies:

| When | Values | Right |
|---|---|---|
| both extractors agree | 104 | 98.1% |
| only one finds the value | 18 | 100% |
| they disagree: the rules value | 17 | 47% |
| they disagree: the LLM value | 17 | 18% |

So agreed and single-source values are accepted, and a disagreement goes to a person, since
neither side is reliable there. Values are also held for review when a company's total does not
equal Scope 1 + 2 + 3 within 5%: Accor's LLM values fail this check (690 + 2,767 + 4,042 kt
against a total of 6,849 kt), and so do the SBTi-scope totals the LLM reads for Saint-Gobain's
2024, which do not match the hand-labelled scopes. Hand-labelled values always win.

**Agreement is not proof.** Vinci prints a baseline-year column before 2025
(`Total Scope 3 | 50,040 | 48,037 | 48,039`, baseline then 2025 then 2024; the text below the
table confirms 48 Mt for 2025). Both extractors shifted every value by one column, so their
agreed Scope 1 for 2025 is the baseline (2,561 kt) instead of 1,985 kt, and the accounting check
cannot see it, because the baseline column adds up too. `--review DG` sends all of Vinci's
values to a person. On the gold set, the companies with a disagreement were no more likely to
have a wrong agreed value, so whole-company review is not triggered automatically.

The result is 396 values for 39 companies, with 58 values in 9 companies waiting in
`data/review/review_queue.csv`.

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

- Review the 58 queued values, Vinci's included.
- Label a new held-out set to measure the extractors after the fixes.
- Estimate the missing values (Eurofins Scope 3, partial disclosures) with a model that
  returns a range rather than one number.
- Investor metrics (PAI 1-3, WACI) on the cleaned data: see `docs/portfolio_metrics.md`.
