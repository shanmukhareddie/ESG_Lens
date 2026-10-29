# Climate targets (ESRS E1-4)

`src/read/targets_extract.py` reads each report's emission reduction targets with the same LLM
as the emissions (gpt-oss-120b on Groq), and `src/load/targets_to_supabase.py` loads them into a
`targets` table (`src/targets_schema.sql`).

## What counts as a target

An absolute cut in the company's own Scope 1, 2 or 3 emissions, as a percentage, by a year after
2025. Intensity targets, financed-emissions targets of banks and insurers, energy targets and
net-zero pledges without a percentage are left out, as in the 26 hand-labelled targets of
`data/gold/gold_targets.csv`. A Scope 3 target limited to some categories still counts as Scope 3.

## Method

1. **Pages.** Targets are repeated across a report (strategy, key figures, E1-4), so the page
   finder is judged on whether the labelled targets are on the pages it picks, not on matching
   the labelled page. Keyword scoring, top 4 pages: 18 of the first 19 labelled targets are on them.
   Counting target-like sentences as an extra signal did not change that.
2. **Extraction.** JSON validated by a pydantic schema (scope from a fixed list, target year
   after 2025, percentage between 0 and 100), one retry with the errors, every reply cached.
3. **Evidence.** A target is kept only if its quote is printed in the report and contains its
   percentage. When the model names the wrong page (it often quotes a repeated target from
   another of the pages it was given), the quote is looked up on those pages and the page fixed.

## Results on the 11 labelled companies

| | |
|---|---|
| Labelled targets found, right percentage | 22 of 26 (85% recall) |
| Base year right | 23 of 26 |
| Returned targets that match a label | 22 of 25 (88% precision) |

The labels first held 19 targets, the main ones per company, and the LLM scored 79% recall and
60% precision against them. Of the 10 returned targets with no matching label, 7 turned out to
be real targets the labels did not list: Capgemini's −90% Scope 1+2 by 2040 and −50%
purchased-goods Scope 3 by 2030, LVMH's 32.5% Scope 3 by 2033 (the label recorded the 23%
milestone LVMH derives for 2030), and four rows of Renault's target table. Each was checked on
its page and added to the labels, which gives the scores above. The three remaining are
debatable perimeters: AXA's own-operations target, Renault's Europe-only 2040 target, and
Renault's world-wide 2030 target (−62.5%) where the label takes the industrial perimeter (−67%).
Capgemini also has −90% targets for 2040 on several Scope 3 categories, which neither the
labels nor the LLM list separately.

Missed: Airbus (its −63% sits in an emissions table as a change, not as a sentence), AXA's
Scope 1+2 −60% (the model returned the own-operations target instead), TotalEnergies' −40% net
Scope 1+2, and Renault's industrial −67%.

## The other 29 companies

53 targets for 21 more companies pass the evidence checks; 8 companies have none, the banks
among them, as expected. These are not labelled. A read-through found two clear errors:
Dassault Systèmes' −77.6% is the progress achieved in 2025 shown next to the 2027 target, and
Pernod Ricard's 30.3% FLAG target is tagged as all scopes. On the site, these targets are shown
as "read by the LLM" and the labelled ones as "checked by hand".

`data/processed/targets.csv` holds the final table: the labelled targets for the 11 labelled
companies and the extracted ones for the others, 79 targets for 32 companies.

## Next

- Label targets for a few more companies to measure precision outside the development set.
- Compare each company's trajectory with its target: the 2025 emissions against the straight
  line from base year to target year.
