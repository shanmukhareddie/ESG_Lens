# Second held-out test

The first test set (Schneider Electric, Saint-Gobain, Kering, SNCF) found two bugs, in the
rules parser and in the unit check. Both were fixed, which used that test set up: its scores
after the fixes are no longer blind. This second set measures the fixed extractors on four
reports that neither extractor's output had been looked at for.

## Labels

48 values in `data/gold/test2_labels.csv`, read from the rendered pages, in the same format as
the gold set. The four companies are chosen for different kinds of report:

| Company | Sector | Page | What makes it a test |
|---|---|---|---|
| Legrand | Industrials | 144-145 | The 2022 base-year column comes before 2024 and 2025; Scope 3 and totals are on the next page |
| Société Générale | Bank | 326 | Scope 3 (77 Mt) includes financed emissions |
| Hermès | Luxury | 233 | Totals labelled over two lines; the market-based total uses Hermès' own "including contractual instruments" Scope 1 and 3 |
| Dassault Systèmes | Software | 116 | Totals are called "Carbon Footprint" |

For every company and year the totals equal Scope 1 + 2 + 3 (to the tonne), except Hermès'
market-based total, which is built from its contractual-instrument figures (noted in the labels).

## Results

`python -m src.validate.evaluate --gold data/gold/test2_labels.csv --out data/processed/test2/evaluation.csv rules=data/processed/rules_extractions.csv llm_v2=data/processed/llm_extractions.csv`

| Extractor | Correct | Precision | Recall | Missed | Wrong |
|---|---|---|---|---|---|
| Rules | 40/48 | 100% | 83.3% | 8 | 0 |
| LLM | 48/48 | 100% | 100% | 0 | 0 |

Neither extractor returned a wrong value. The rules missed the eight totals of Hermès and
Dassault Systèmes, whose labels ("Total GHG emissions (scope 2 location-based and scopes 1 & 3",
"Carbon Footprint") are not in the taxonomy. The LLM read all 48, including Legrand's
base-year-first layout and Hermès' wrapped labels.

## What it shows

- The LLM scores higher on both test sets than on the development set (87% precision, 78%
  recall): test set 1 gave 100% and 78% blind, then 96% and 96% after the fixes; test set 2
  gives 100% and 100%. The development set is the harder one because it holds the layouts that
  motivated the fixes (Orange's segment columns, L'Oréal's wrapped headers).
- The rules are precise once their parser bugs are fixed, but they only find labels they
  were written for. That is the case for keeping the LLM as the main reader and the rules as
  the cross-check: when the two agree, the value was right 98% of the time.
- Four companies are a small sample. 48 out of 48 means the error rate on reports like these
  is probably low, not that it is zero: Vinci's baseline column fooled both extractors.
