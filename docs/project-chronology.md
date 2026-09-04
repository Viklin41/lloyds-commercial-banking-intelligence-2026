# Project chronology, every stream, every branch

**Built 8 August 2026** from a read-only crawl of all eight branches (six agents, one per branch
group), cross-checked against commit dates and stored notebook outputs. This is the record we
narrate the report from: what we did, when, why it mattered, and why it stopped or was superseded.

**Updated 25 August 2026** from a fresh fetch of all twelve remote branches. Streams A to G are
unchanged and stand as written. Stream H has been rewritten, because the dashboard it described was
replaced by a different architecture two weeks later. Streams I to N are new and cover 8 to 25
August, and a sixth measured negative (N6) has been added. The companion document `drafts/dashboard-deep-dive-2026-08-25.md` is the full technical
reference for the dashboard as it now stands: how it fetches data, how filters, sorts, presets, views
and pages are defined, and what it takes to wire a new file into the UI.

Nothing here is a plan. Where a number is contested or was later corrected, both values are given.

---

## The two re-organisations, which are the spine of the story

The project reorganised itself twice, and both reorganisations were driven by evidence rather than
by preference. That is the narrative arc of the whole report.

**Split 1, by client need (early June).** The client brief names three teams, so we mirrored it:
Growth (Viktor and Vishal), Attrition (Samuel), Existing Relationships (Sneha). It broke within
about two weeks. Every one of us was pulling the same Companies House bulk file and deriving
overlapping variables from it, because the three "needs" are not three datasets, they are three
questions asked of one dataset. Samuel's attrition branch stops on 22 June and Sneha's branch is
pruned to a single notebook on the same day; that date is the seam.

*(Dating note, carry this into the report as a footnote: no commit message states either
reorganisation. The ~22 June date is inferred from those two branches stopping and being pruned on
the same day, and the second split is inferred from what people started working on afterwards. It
is circumstantial evidence, correctly signposted, rather than a record.)*

**Split 2, by data type (late June).** Viktor and Vishal took unstructured, Samuel and Sneha took
structured. This one held, but it also broke in a more interesting way: the unstructured half
measured its own coverage and found there was almost nothing there for companies of this size.
Viktor left the news stream and moved onto the structured time series; Vishal continued into the
Gazette; Samuel continued into alternative registers; Sneha moved onto the SHAP baseline with
Viktor. The final shape (a structured predictive core plus a measured negative result on
unstructured breadth) is the consequence of that second break, not of a plan.

---

## Stream A. The Companies House foundation (Viktor, 6 to 19 June)

**Branch:** `main`. **Notebooks:** `01_companies_house`, `02_companies_var`, `03_company_risk_signals`.

| Date | What |
|---|---|
| 6 Jun | Initial EDA on the bulk register |
| 7 Jun | Sector and turnover filtering logic; Account Category description and SIC code mapping CSV |
| 11 Jun | Bulk filtered CSV produced |
| 19 Jun | Filtering revised to include **all** firm sizes; notebook automated so a fresh clone can fetch the bulk file itself |

Downloads the ~470MB Companies House bulk product (`BasicCompanyDataAsOneFile-2026-06-01`,
**5,698,276 companies**), scrapes a 731-code SIC lookup, maps 325 SIC codes onto three target
sectors (Technology/legal/professional 55, Manufacturing 259, Fast growth and emerging 11), filters
to Active, and tiers by size off `Accounts.AccountCategory`. Output
`data/processed/filtered_bb_sme_sectors.csv`, **1,372,321 companies x 56 columns**.

**Why it matters:** this is the universe every other stream keys on, and the 1,372,321 figure
recurs in three independent places later (Sneha's notebooks, the SHAP feature matrix, and the
`Trading` bucket of Vishal's widened universe). The join key is `CompanyNumber`, zero-padded to
eight digits, and the discipline of that single decision is why the branches merge at all.

**Superseded:** no. Still live. The 19 June revision (all sizes, self-fetching) is what made it
reusable.

## Stream B. Vishal's parallel filtering attempt (Vishal, 7 June, abandoned same day)

**Branch:** `vishal/filtering`. **Notebook:** `companies_house.ipynb`. **One commit.**

The same task as Stream A, done independently on the same day: sector filter, Active filter, and a
size proxy mapping `Accounts.AccountCategory` to BB (under GBP 3m) and SME (GBP 3-25m). It ran on
`nrows=50_000`, a 50k-row slice, not the full register: 6,219 sector matches (12.4%), 5,579 after
the Active filter, 3,424 after the size filter, splitting BB 2,065 / uncertain 1,241 / SME 118.

**Why it stopped:** duplicated effort discovered immediately. Viktor's version continued through 19
June and became `01_companies_house.ipynb`; this branch has no commits after 7 June.

**What it is worth in the report:** one paragraph, and an honest one. None of its counts are usable
because they come from a 50k sample, but the *logic* survived, the account-category-to-turnover
size proxy and the sector-to-SIC mapping both carried into the pipeline that replaced it. It is
also the cleanest example of the coordination cost of Split 1.

## Stream C. Samuel's attrition workstream (Samuel, 9 to 22 June, superseded)

**Branch:** `samuel/attrition`. **Notebook:** `attrition_analysis.ipynb`. 9 commits.

| Date | What |
|---|---|
| 9 Jun | Attrition engine: definitions, CH API client, EDA, tests; validated on the live API; baseline EDA on the full 5.7M register; sampling and charge-enrichment scripts |
| 11 Jun | Recent-loss signal, filing-history attrition labels, grouped static dataset, first news pipeline |
| 22 Jun | Restructured into subfolders; financial notebook moved out |

Splits "attrition" into three phenomena that need different signals: dormancy, closure/distress,
and bank-switch (a healthy firm moving borrowing to a rival). Builds a Companies House REST client
(charges, filing history) keyed correctly on `company_number`, plus a GDELT news lookup keyed on
cleaned company **name**, which the notebook itself flags as the weak link.

**Numbers:** 11.5% dormant, 9.2% in distress, 14.3% hold any loan. Loan prevalence rises steeply
with size: BB 10.9%, SME 27.1%, Large 62.5%, Midcorp 83.2%. Distress highest in wholesale and
retail (11.5%) then manufacturing (10.2%). Bank-switch detected in about 12.5% of borrowing firms.

**The finding worth keeping (N3): losing a bank does not predict distress.** 7.2% of firms that
later hit distress had lost a bank in the prior 24 months, against a 5.5% baseline for firms with
no distress event. It is a coincident, descriptive signal, not a predictive one. This rules out an
intuitive hypothesis by measurement, which is exactly the kind of result the report should lead
with.

**Second finding:** 0 of 100 sampled BB/SME firms had any GDELT news coverage in a year. This is
the *first* independent sighting of the coverage problem, six weeks before the news lab measured it
properly. Worth saying so, because three independent measurements of the same negative is much
stronger than one.

**Why it stopped:** Split 2. The concept survived, the attrition target was renamed `voluntary_exit`
on 26 July in `15_targets.ipynb` and is one of the four modelled targets. The standalone notebook
was superseded by the integrated pipeline; its definitions were not.

## Stream D. Sneha's existing-relationships work (Sneha, 12 June to 3 July)

**Branch:** `sneha` (also present on `sneha-viktor/shap`; cite the latter).

| Date | What |
|---|---|
| 12 Jun | Bulk-data setup, notebook renames |
| 13 Jun | `04_exiting_relationships.ipynb` first upload |
| 22 Jun | Branch pruned to the relationship notebook only (the Split-2 seam) |
| 25 Jun | Relationship notebook re-added; `05_director_changes` placeholder created |
| 28 Jun | `05_contract_finder.ipynb` first pass; `06_director_changes.ipynb` |
| 3 Jul | Contract finder rewritten with full EDA and narrative; `01_companies_house` re-added as the shared base |

**`04_exiting_relationships.ipynb`, separating LBG clients from everyone else.** Loads the 1,372,321
base, derives company age, `has_any_charge`, `has_outstanding_charges` and a debt ratio, then calls
the Companies House Charges API for companies with outstanding charges. Lender names are
keyword-matched against an LBG-group list (Lloyds Bank, Bank of Scotland, Halifax, MBNA, HBOS) to
classify Lloyds-linked against other. Capped at `API_LIMIT = 100`: **100 companies, 331 charge
records.** It also carries a large hand-written map of Lloyds product lines to signal flags that is
directly liftable as report prose.

*Later repurposed:* yes, and this is the important part. The LBG-versus-competitor classification
here is the seed of the lender panel in `14b_lender_charges`, which scaled the same idea to
158,684 companies and 558,693 charges. The 2,735,406-row service-flag table is **out** of the
report: it is one row per company per applicable flag, and with only 100 companies ever checked,
99.99% of it reads "not checked by API".

**`05_contract_finder.ipynb`, public procurement.** Contracts Finder OCDS API, award-stage,
cursor-paginated, 18-month window. 6,000 releases to 5,715 unique OCIDs to 2,154 clean contract
rows to **1,317 company-level rows**. Only 43.0% joined back to the BB/SME base, as expected since
many winners are large or out-of-sector. Buyer side returned zero companies because public bodies
carry a government scheme id, not `GB-COH`, which the notebook states as a known limitation rather
than a bug. Concentration: 78.2% of winners won exactly one contract; top 50 hold 73.6% of value.

*Later repurposed:* yes, as `14_contracts_asof` in the modelling pipeline. **Value-based statistics
are out** of the report: about 40 medical suppliers each carry the full GBP 543m of one framework
award, which drives the GBP 17.1m mean and the 73.6% concentration. Counts only.

**`06_director_changes.ipynb`, governance and capital signals.** Officers API for appointments and
resignations over 18 months, Filing History API for SH01 share allotments as a capital-raise proxy,
plus a financial-health flag (outstanding charges, or overdue accounts, or accounts stale over 24
months). `API_LIMIT = 1000`. Outputs `director_growth_enrichment.csv` and `financial_health.csv`,
1,000 rows each.

*Not used in the modelling pipeline.* Worth a paragraph anyway: it is the clearest statement in the
project of the per-company API ceiling. 1,000 companies at 0.5s each against a 1.37M universe is
about eight days of wall clock for one pass, which is the constraint that forced everything
predictive onto the bulk product and the batched Charges harvest.

## Stream E. The unstructured data lab (Viktor and Vishal, 21 June to 26 July)

**Branch:** `viktor-vishal/unstructured-data-lab`. 13 commits. This stream produces the project's
headline negative result, and it is the reason the architecture looks the way it does.

| Date | Who | What |
|---|---|---|
| 21 Jun | Viktor | `02_companies_var` EDA refined to segment the population |
| 21 Jun | Vishal | First news feasibility test, NewsAPI against Guardian (becomes `API.ipynb`) |
| 23 Jun | Vishal | GNews added to the bake-off |
| 23 Jun | Viktor | `04_coverage_stress_test_sample`, the balanced 96-company grid |
| 2-3 Jul | Vishal | `08_news_api_large_coverage`, then `09_guardian_methodology` |
| 5 Jul | Viktor | `05_newapi_lab`, the six-level query methodology |
| 26 Jul | Vishal | `10_news_sentiment_model` parts B and C, the Gazette crawl |

**`API.ipynb`, the bake-off (Vishal, 21-23 Jun).** Stratified 72-company sample (3 sectors x 3
segments x 8), Dormant/No-Filings/Large/Subsidiary excluded. GDELT was abandoned first: a 429 rate
limit, and the author's IP was banned for querying too fast. Raw, unverified hit rates on the
remaining three: **NewsAPI 6.9%, GNews 4.2%, Guardian 2.8%.** Superseded by NB09's stricter method,
but it stands as the first data point and it is where the rate-limit discipline came from.

**`04_coverage_stress_test_sample.ipynb` (Viktor, 23 Jun).** Infrastructure, no API calls. Builds
the reusable **96-company balanced grid**, 4 size tiers x 3 sectors x 8, deliberately
non-representative so the rare Medium and Large cells have a measurable n. Also defines
`normalise_search_name` and the sector-specific query templates. Output
`data/processed/nb04_stress_test_sample.csv`, and every later coverage number in the project is
measured on this sample. Kept.

**`05_newapi_lab.ipynb` (Viktor, 5 Jul).** The query-methodology deep dive, Level 1 (bare name)
through Level 6 (domain filters), on a 12-company subsample deliberately weighted toward companies
*likely* to have coverage (PLC status, group accounts, mortgage charges, age), with that bias
stated. It makes the disambiguation problem concrete: bare "Peco" returns 42 results, almost all
PECO Energy of Pennsylvania and PECO Pallet of the US, while the exact phrase "Peco Services"
returns 0. NCC Group plc acts as a semi-positive control and survives every filter down to 9
verified articles. This is where the exact-phrase plus corroboration rule was designed, and NB09
implements it.

**`08_news_api_large_coverage.ipynb` (Vishal, 2 Jul), superseded and discredited.** Runs Guardian
plus a second API across all 96 companies. NewsCatcher CatchAll was abandoned mid-notebook, it is an
async job queue with a 10-15 minute wait per query, impractical at 96 companies. **Its headline
figure of 92/96 companies (95.8%) and 22,822 articles is not a result.** The exported signal table
shows identical article counts and identical sentiment scores repeated across every company in the
same segment-by-sector cell (all eight Large / Fast-growth firms show exactly 249 articles,
VADER 0.030, TextBlob 0.061). That is a broadcast or merge bug collapsing per-company results to a
per-cell constant. NB09's own prose says NB08 "wasn't using a properly tuned query, it was mostly
giving false positives". **Out of the report as a result, in as a one-line correction.**

**`09_guardian_methodology.ipynb` (Vishal, 2-3 Jul), the canonical measurement.** Guardian Open
Platform `/search`, `query-fields=body`, exact-phrase on the cleaned name, three-year window
(30 Jun 2023 to 30 Jun 2026), sections restricted to business, money, technology and uk_news, run
against Viktor's 96-company grid.

- **Positive control, Tesco:** 1,209 articles bare, 571 with the section filter, 585 with
  `query-fields=body`. The API, key, window and filters all work, so the zeros are real.
- **Raw:** 5 of 96 companies had at least one article (5.2%), 83 articles in total. By tier: Large
  8.3%, Medium, Micro and Small 4.2% each.
- **Verified after disambiguation:** **0 of 96 companies, 0 of 83 articles.** Disambiguation
  required the exact phrase plus corroboration on town, sector or context, with town mandatory for
  single common-word names. All five apparent hits were name collisions: "Baroness" returned
  Michelle Mone stories, "Coaster" returned unrelated pieces using the common word, "Ncc" returned
  the acronym rather than NCC Group, plus "Brs Golf" and "Ashtons (Sheffield)".

**This is finding N1**, and it now has three independent sightings: Samuel's 0 of 100 on GDELT
(9 June), the bake-off's 2.8-6.9% raw (21 June), and this 0 of 96 verified (2 July).

**`10_news_sentiment_model.ipynb` parts B and C (Vishal, 26 Jul), the Gazette crawl.** Part A is a
near-verbatim copy of NB09 (with a stale header) and adds nothing. Parts B and C are new and are
the counterweight to N1.

The Gazette has no company-name search, only category, date and postcode, so notices are pulled in
bulk and matched back through the `CompanyNumber` printed in each one. One request per 10 seconds,
cached per page and resumable, about 7.6 hours for the category-24 crawl, a caution learned directly
from the GDELT ban. Volume: 273,915 corporate-insolvency notices plus 10,317 companies notices over
three years, **284,230 extracted**, 274,904 after dropping roughly 10.9k ceremonial notices
(Honours, Proclamations). **57.0% of insolvency notices carry a parseable `CompanyNumber`**
(156,768 kept); the remaining **43.0% are name-only and were deliberately excluded rather than
fuzzy-matched**, leaving 84,815 distinct unmatched names as a stated upper bound. Output
`nb10_gazette_company_features.csv`, **106,664 companies x 52 engineered variables** (counts, flags,
recency, frequency, a five-stage distress ladder, severity, geography, provenance).

**And then finding N5.** Left-joined onto the 1.37M Active universe, only **1,033 companies
(0.075%)** carry a live Gazette signal, of which 773 have a notice in the last 90 days. The source
that genuinely reaches SMEs reaches them only once they have stopped being Active. The notebook
frames this correctly as a feature library rather than a risk score.

**Housekeeping, not a report item: committed API keys.** `API.ipynb` carries literal NewsAPI,
Guardian and GNews keys; `08_news_api_large_coverage.ipynb` carries NewsCatcher and GNews keys.
NB09 and NB10 load from the environment instead, which is the practice that was adopted afterwards.
These need rotating before anything is shared.

**Why the stream stopped:** it did not fail, it finished. Once the coverage was measured three ways,
continuing to chase narrative media would have been spending the remaining weeks re-confirming a
known zero. Viktor moved to the structured time series; Vishal continued to the Gazette, which is
the correct response to the finding rather than an abandonment of it.

## Stream F. Samuel's spine crosswalk and alternative registers (Samuel, 22 June to 10 July)

**Branches:** `samuel/financial` (one commit, 22 Jun) and `samuel/spine-crosswalk` (25 Jun to 10 Jul).

**What the spine crosswalk actually is**, in one paragraph, because it has never been written down
plainly. It is a small local knowledge graph in a DuckDB file (`lloyds.duckdb`) with three tables.
The **spine** is one row per UK company keyed on Companies House number, **869,043 companies**. The
**identifiers crosswalk** links each spine company to its other names and codes (previous trading
names, LEI, ticker), one row per link, each tagged with a source and a confidence score where 1.0
means exact and lower means inferred. The **signals** table is an event log (company, event type,
date, confidence) that every later source notebook writes into. It exists because outside data
sources name companies four different ways, by number, by LEI, by ticker, or by free text, so a
translation layer had to exist before any outside signal could be joined. It is genuinely used:
notebooks 06 through 09 all read the spine and write to `signals`.

| Date | What |
|---|---|
| 22 Jun | `financial_data.ipynb` and `financial_sentiment.ipynb` (branch `samuel/financial`) |
| 25 Jun | NB05 builds the spine, the crosswalk and the empty signals table; NB06 Contracts Finder; `duckdb` and `rapidfuzz` added |
| 26 Jun | Plain-English annotation pass; cleanup; `README_notebooks_5&6.md` |
| 8 Jul | NB07 Adzuna hiring; NB05 made re-runnable without wiping signals; the financial notebooks consolidated onto this branch |
| 9 Jul | NB08 Land Registry CCOD property ownership |
| 10 Jul | NB09 IPO trade marks |

**Coverage of the 869,043-company spine, which is the whole point of this stream:**

| Source | Keys on | Coverage | Verdict |
|---|---|---|---|
| CH previous names | exact CH number | 130,945 rows / 107,776 companies (12.4%) | usable, exact |
| **LEI** (GLEIF + Wikidata) | CH number | **855 companies, 0.10%** | measured dead end |
| **Ticker** | CH number | **0 companies, 0.00%** | measured dead end |
| Land Registry CCOD | CH number, name+postcode fallback | **5.25%**, the widest SME reach found | usable, England and Wales only |
| IPO trade marks | name + postcode area | 9,063 companies, 1.04% | soft enrichment, weakest confidence |
| Contracts Finder | CH number, then name+postcode | 239 companies, 0.03% | skews to large suppliers |
| Adzuna, per company | exact name + town | **1 advert of 1,000 matched** | dead end |
| Adzuna, by sector/region | no company join | full | context only, not a company signal |

**The correction that has to be in the report.** LEI coverage was first reported as **9.14%**. That
was an orphan-join artefact: the GLEIF and Wikidata pulls returned every UK company holding an LEI,
and rows were being counted for companies not in the spine at all. Corrected by storing crosswalk
rows only for spine companies and counting through a proper join: **0.10%**. Finding and stating
that is worth more than the original number would have been.

**Three more corrections, all of the same family (name matching without a location check is
dangerous):** a small Oxford "AMAZON LTD" was credited with AWS cloud contracts; a company beginning
"& THE NEW" was credited with New Era Fuels' contract; "ACE TAX LTD" was credited with taxi
contracts. Fixed by requiring postcode agreement, which first dropped matching to zero because
Contracts Finder buries the postcode in a free-text address field, then recovered to 94% supplier
postcode coverage via regex extraction. Separately, two early full-scope runs silently used a
leftover `SAMPLE_N = 50,000`, an alphabetical first slice, producing artificially small match counts.

**`financial_data.ipynb` and `financial_sentiment.ipynb`:** 26 hand-picked UK-listed firms via
`yfinance` (market cap, margin, one-year return, one-year volatility). The sentiment half was
written and **never executed**, zero stored outputs, so no sentiment-versus-return correlation has
ever been produced. The notebook itself says these are listed firms and do not reach the private SME
population, which the 0.00% ticker coverage then confirms independently. **Out** of the report as a
result; **in** as one documented dead end in Background.

**The lesson this stream contributes:** SMEs are effectively invisible to market-identifier systems.
A reliable join to this universe requires either an exact Companies House number (Land Registry, the
best at 5.25%) or name matching with a location confirmation. Pure name matching produces
confidently wrong answers, and we have four named examples of it.

## Stream G. Modelling, SHAP and the panel (Viktor with Sneha, 7 July to 8 August)

**Branch:** `sneha-viktor/shap`. This is the predictive core and the largest single body of work.

| Date | Notebook | What, and why it mattered |
|---|---|---|
| 7 Jul | `10_feature_matrix`, `11_shap_sample` | Harmonised the scattered engineered features into one matrix |
| 17 Jul | `12_historical_snapshots` | 33 monthly snapshots, the 49.6M-row panel: the project stops being cross-sectional |
| 18 Jul | `12_baseline_model` (Sneha) | First insolvency baseline; superseded, but its `is_insolvent` enumeration survives |
| 20-25 Jul | `13_panel_deltas`, `13a_delta_eda` | ~25 backward-looking deltas on a dense calendar spine |
| 25 Jul | `14_contracts_asof`, `14a_name_matching` | Procurement joined as-of each month |
| 26-27 Jul | `15_targets`, `15b_target_eda` | The four self-labelled targets and their anatomy |
| 27-28 Jul | `16_shap_models`, `14b_lender_charges` | `baseline` run recorded; the 25.4-hour Charges harvest |
| 6 Aug | `16_refactor_run`, `16_lender_run` | The control run, then the lender A/B that returned P@100 = 1.000 |
| 7 Aug | `nb16_lender_leakage_fix`, `14b` rewrite, `17`, `18`, `19` | The audit day: leak diagnosed and fixed over four passes, growth defect found, determinism and intervals added, three claims retracted |
| 8 Aug | gate recalibration, `19_final_comparison` | Gate recalibrated to 4d/1d, all six configs re-run with bootstrap CIs |

**`10_feature_matrix` and `11_shap_sample` (7 Jul).** One row per company across three layers: raw
Companies House columns, static engineered features for everyone, and API-derived features for a
prioritised sample with a sentinel elsewhere and an `api_enriched` flag. Output
`data/processed/shap_feature_matrix.parquet`, **1,372,321 x 91**, 200 companies live-enriched, plus
`reports/shap_feature_catalog.md`. NB11 adds a rate-limit-aware incremental recipe for growing the
API sample (about 1,800 calls/hour, never re-calling an enriched company) and states the discipline
that persists through the whole project: **never analyse an API-derived column on the full 1.37M
frame, the sentinels poison the statistics, always filter on `api_enriched`.**

**`12_historical_snapshots` (17 Jul), the pivot.** Acquires 33 monthly bulk zips (Oct 2023 to Jul
2026; **June 2025 is genuinely missing from the Companies House server**) and builds the
company-month panel with a two-pass design, universe union then per-month extract, which is what
stops sector re-coding being mistaken for dissolution. **49,556,152 rows, about 2.04M companies.**
Verified to reproduce notebook 1 exactly at June 2026 (1,372,321 rows, identical sector counts).
`today=snapshot_date` is passed explicitly to the static feature code so "now" cannot leak into
history. *Caveat for the writer: this notebook has no stored cell outputs, its numbers come from
commit messages and downstream notebooks.*

**`13_panel_deltas` and `13a_delta_eda` (20-25 Jul).** About 25 strictly backward-looking deltas at
3, 6 and 12 months, computed on a **dense 34-month calendar spine rather than a positional `LAG`**,
so the June 2025 hole produces honest NULLs instead of silently wrong four-month deltas. Row count
must equal the panel exactly, and does. 13a adds three features that close the "stopped filing" gap
(`months_since_last_accounts_filing`, `months_since_last_confstmt`,
`accounts_stale_streak_months`) and establishes that lending and distress signals point in opposite
directions, non-Active companies take *fewer* new charges, which is why the four targets stay
separable.

**`14_contracts_asof` and `14a_name_matching` (25 Jul).** The Procurement Act 2023 split publishing
between Contracts Finder (legacy) and Find a Tender (new) on 24 February 2025, so both bulk OCDS
feeds were harvested and unioned; without that the data shows a purely regulatory decay artefact.
2,633 cross-source duplicate awards were found and removed. **173k awards over 44.6k companies**,
against Sneha's earlier API-paged 2,154 over 1,317, which is the scale difference between an API
and a bulk feed. Contract winners are about **7.5x** more likely to take a new charge, and first-time
winners are the fastest-growing group. NB14a widens coverage from 1.0% to 1.6% of the panel with
normalised-name plus postcode matching, measured at **88% precision on name alone and 92% with
postcode** over ~100k labelled records; matching against the full register rather than the narrow
three-sector universe was shown to be necessary, the narrow version manufactures false positives.
The extended set is kept as a separate A/B directory and the strict set stays the default for
anything a relationship manager would see.

**`15_targets` and `15b_target_eda` (26-27 Jul).** Features from month `t`, labels strictly from
`t+1..t+H`. Four targets: **Lending Readiness** (charges increase, H=3m, base rate 0.25-0.31%),
**Credit Risk Exposure** (genuine insolvency, H=6m, 0.30-0.41%), **Voluntary Exit** (strike-off
proposal, H=6m, 6.7-8.5%), **Growth Signal** (size-tier upgrade, H=12m, 2.1-2.2%). Two corrections
worth reporting: distress was redefined from "non-Active" (90% of which was benign strike-off) to
genuine insolvency only; and voluntary exit was redefined from state-at-`t+H` (3.5%) to
event-anywhere-in-window (7.2%), because about half of strike-off proposals are withdrawn but still
mark a real distress moment. Negatives downsampled 10:1 with `neg_keep_rate` carried per row so
recalibration still works. `FIRST_FULL_ORIGIN = 2024-10` is set here, and the fact that `growth`
cannot reach it without losing sample size is the seed of the NB18 defect. 15b establishes that
size is by far the strongest cut (30x spread on lending, Micro 0.09% against Large 2.74%) and that
growth's strongest univariate feature is an *inverted* tier rank, a ceiling effect since Large
companies cannot grow further.

**`14b_lender_charges` (28 Jul, rewritten 7 Aug), counterparty identity.** Charges API harvest,
**158,684 companies, 558,693 charges, 25.4 hours, zero 404s**, collapsed onto institutions by an
ordered regex taxonomy classifying **77.5%** of charge-lender rows. Thirteen lender features
including `is_lbg_client`, `n_competitor_lenders` and `competitor_entered_12m`. The league table is
itself a finding: **NatWest 16.4%, LBG 12.1%, Barclays 12.0%, HSBC 11.9%.** A fifth `switching`
label was built but **not trained**: 797 positives against a pre-set 1,000-positive stop rule, so it
ships as three rule-based feeds instead. Pre-registering that threshold and then honouring it is
worth a sentence in the report.

This is also the notebook the leak lived in. Its "Check 2" cell described the mechanism months
before anyone recognised it as leakage, and its original verification 7 was a test that could not
fail by construction, because it replayed the harvest against `created_on`, the same wrong clock.

**Notebooks 16 to 19 and the audit day.** Full detail is in `drafts/remediation-story-2026-08-08.md`
and section 11 of `drafts/next-steps-2026-08-07.md`. In short: `refactor` is the clean control that
isolates "we added a model family" from "we added features"; `lender` returned P@100 = 1.000 on
`lending`, which is a leakage signature (perfect top-of-list next to a barely-moved AUC) rather than
a win; the gate was fixed over four passes, `created_on` to `delivered_on` to a flat 21-day margin
to a properly calibrated 4-day/1-day gate, and 18 of the original 21 days turned out to be the
unlagged **satisfaction** clock rather than a visibility lag. NB18 found nine `growth` features that
were 100% NULL in every training origin and populated in test, cutting growth from 41 features to
27. NB17 added determinism, bootstrap intervals and per-origin metrics, and produced two methods
findings: pooled precision@N is **not** an average of its months (it lands outside their range in 9
of 12 rows), and `voluntary_exit` P@N is partly arbitrary because 982 of its top 1000 scores are
exact ties. Three claims were retracted during the day, including an MLP improvement whose sign
flips across seeds.

**The run registry, eleven recorded runs.**

| Tag | What it tests |
|---|---|
| `baseline` | First recorded run, 41 features, LightGBM and logistic. Fixed historical reference |
| `refactor` | Control, same 41 features and `feature_hash`, adds the MLP |
| `lender` | 54-feature A/B, **leaking**, never quote its `lending` numbers |
| `lender_fixed` | `delivered_on` gate, still leaking (P@500 0.742 against 0.282) |
| `lender_asof21` | Flat 21-day margin, superseded by the calibration |
| `refactor_det` | `refactor` with determinism, intervals, per-origin metrics. **The control everything is read against** |
| `lender_asof21_det` | The A/B re-baselined under determinism |
| `refactor_growthfix` | Control with growth cut to 27 features. **The model that produced the shipped shortlists** |
| `lender_calib` | Calibrated gate point estimate, 4d/1d |
| `lender_calib_lo` | Loosest gate tested, 2d/1d, shows the gradient |
| `lender_calib_hi` | Most conservative gate, 7d/3d. **The run the lender verdict is read off** |

**`src/` module map**, which is what makes the "this is engineering, not notebooks" argument:
`data/ch_bulk` (snapshot manifest and download), `features/ch_static`, `features/ch_api`,
`features/sample`, `features/panel`, `features/contracts`, `features/matching`, `features/charges`
(the gate, and the site of the defect and its fix), `features/lenders` (the lender regex
dictionary), `models/targets`, `models/train` (split, registry, recalibration, precision@N, SHAP,
bootstrap, run recording), `models/report` (writes figures and tables straight out to LaTeX).

**The commercial output (8 Aug):** `reports/shortlists/`, top 100 per target for July 2026 from
`refactor_growthfix`, 398 unique companies across the four lists. Per held-out month:
lending 0.43 and 0.41 at a 0.26% base rate (**about 150x lift**), insolvency 0.16 and 0.14 (~45x),
growth 0.22 (~10x), voluntary_exit 0.85 and 0.78 (~10x, and the weakest despite looking the best).
Read lift, not precision.

## Stream H. The dashboard MVP (Vishal and Samuel, 4 to 5 August), superseded by Stream L

**Branch:** `vishal-samuel/harmonisation`. One commit, `147c078`, 5 August.

*Read this section as history, not as a description of the current dashboard.* Everything below was
true on 8 August and none of it is the architecture that shipped. The precompute-then-serve store,
the 10.6MB `data.js`, the 19,347-company coverage, the "1 of 7 sources wired" count and the
hardcoded Windows paths were all replaced between 10 and 24 August by a DuckDB query server reading
the Parquet in place. Stream L is what exists now, and
`drafts/dashboard-deep-dive-2026-08-25.md` is the full account of it. The reason to keep this
section is that the two corrections it records, the universe question and the one-join-apart
finding, are both still load-bearing in the report. Design agreed 4 August
in `reports/integration-design.md` and `notebooks/nb11_blueprint.ipynb`.

**Architecture: precompute then serve, with no framework at all.** `dashboard/build_data.py` joins
the widened universe (1,493,972 companies) to the Gazette features (106,664 companies) and notices
(284,230, of which 28,896 survive date and company-number filtering) and writes
`dashboard/data.js`, a 10.6MB `window.STORE = {...}` assignment. `dashboard/index.html` is a single
static page of vanilla JS that reads it. It opens by double-clicking, because `file://` blocks
`fetch()`, so the store is a `.js` assignment rather than `.json`. For a demo on somebody else's
laptop that is the right call and it should be defended in the report rather than apologised for.

**What works today:** search by name or number, four headline stats, a "flagged for review"
watchlist ranked by distress stage then recency, lifecycle filter chips (Trading, Fading,
Distressed, Insolvent), a five-stage distress ladder, a per-company Gazette timeline, and deep
links to the actual notices as evidence.

**Coverage of the store:** 19,347 companies, being 19,097 with a Gazette signal plus 250 random
quiet ones for the empty state, out of 1,493,972. Watchlist by lifecycle: Trading **1,033**, Fading
164, Distressed 27, Insolvent 17,873.

**Sources: 1 of 7 wired.** Gazette is live. News, contracts, hiring, property, trade marks and
grants render as "not connected yet" rather than as zero, which is the honest choice.

**The universe question, settled.** Their widened universe's `Trading` bucket is **exactly
1,372,321**, which is Stream A's filtered set to the row. The two universes already agree; theirs is
ours plus Fading (97,652), Insolvent (23,828) and Distressed (171). Join on `CompanyNumber`, use
their widened universe as the store and our Trading slice as the modelling population.

**The finding buried in the blueprint, which completes the unstructured argument (N5).** Gazette
features cover 106,664 companies, but only **1,033 of them are inside the 1.37M Active universe**,
because a company with a winding-up petition is on its way out of Active status. Their strongest
unstructured source fires on about 1 company in 1,300 of the modelling population. That is not a bug
in either half, it is the same finding as the news result arriving from the opposite direction:
**the public signals that are richest are concentrated on companies that have already failed, which
is exactly when a bank no longer needs a prediction.**

**What is not wired: the model.** The company page has a "Model indices" panel with four correct
targets and horizons, all reading `awaiting file`. There is no adapter and no join, only a
hardcoded block in `leftColumn()` in `index.html`. The spec exists only in the unbuilt blueprint:
a file keyed on `company_number` with `lending_3m`, `insolvency_6m`, `voluntary_exit_6m`,
`growth_12m`, `model_run_date`. That file has effectively existed since 27 July as
`data/processed/scores/scores_<tag>_2026-07.parquet`, 1,409,284 companies with four calibrated
probabilities each. **The two halves of this project have been one join apart for two weeks and
neither side knew.**

*Closed on 10 August.* Viktor built `notebooks/20_dashboard_handover.ipynb` and shipped
`dashboard_bulk_2026-07.parquet` with the four scores already on it (Stream I). All four render on
the company page today, as bands rather than probabilities.

**Rebuild blockers, as they stood on 8 August:** hardcoded Windows paths in
`dashboard/build_data.py` and `notebooks/build_widened_universe.py`
(`C:\Users\visha\Lloyds_Github\...`); the three input CSVs are gitignored and not shipped, so only
the committed `data.js` makes the dashboard openable. No secrets committed on this branch (`.env`
used correctly), which is worth noting because it is not true everywhere else in the repo.

*Path blocker closed.* `dashboard/serve.py` now resolves the data tree from `--data`, then the
`LLOYDS_DATA` environment variable, then the developed-against path as a fallback, and prints exactly
what it looked for when it cannot find the Parquet. The data blocker is unchanged and is inherent:
the Parquet is 64MB and the side files far larger, so nothing runs without a copy of the data tree.

---

# Part two: 8 to 25 August

The crawl above stopped on 8 August. What follows is everything committed since, from a fetch on
25 August covering all twelve remote branches. The shape of this fortnight is different from the
first two months: nobody started a new investigation. Every stream here is either **hardening** (SHAP
figures, per-company reason strings, a news audit that retracted two earlier outputs) or
**delivery** (one Parquet everyone joins to, three more sources, a rebuilt dashboard, a report
draft). That is the right shape for the end of a project and it is worth saying so in the write-up.

**Branch inventory as of 25 August, twelve remotes:**

| Branch | Last commit | Owner | State |
|---|---|---|---|
| `main` | 25 Aug, `af99ae8` | Viktor | **Live.** The LaTeX report draft, 1,663 lines |
| `sneha-viktor/shap` | 21 Aug, `d8b263f` | Viktor, Sneha | **Live.** Modelling core, handover Parquet, SHAP figures |
| `vishal/dashboard` | 24 Aug, `8ebeef6` | Vishal | **Live.** The dashboard as it now exists |
| `samuel/spine-crosswalk` | 13 Aug, `b18434e` | Samuel | **Live.** The three-source dashboard pack |
| `vishal-samuel/harmonisation` | 13 Aug, `458969f` | Samuel | Superseded by `vishal/dashboard`, holds the shipped CSVs |
| `sneha/market-analysis` | 18 Aug, `184001f` | Sneha | **Live.** Competitive market analysis, feeds the Analytics page |
| `sneha/base` | 13 Aug, `af3aadd` | Sneha | Pruned to empty of notebooks |
| `viktor-vishal/unstructured-data-lab` | 26 Jul | Viktor, Vishal | Finished, see Stream E |
| `samuel/attrition` | 22 Jun | Samuel | Superseded, see Stream C |
| `samuel/financial` | 22 Jun | Samuel | Dead end, see Stream F |
| `vishal/filtering` | 7 Jun | Vishal | Abandoned same day, see Stream B |

## Stream I. The handover Parquet (Viktor, 10 August)

**Branch:** `sneha-viktor/shap`, commit `40edc17`. **Notebook:** `20_dashboard_handover.ipynb`.
**Doc:** `reports/dashboard_handover_columns.md`, 370 lines.

This is the join that Stream H said the project had been two weeks away from making, and it is the
single most consequential commit of the fortnight, because everything downstream keys on it.

`data/handover/dashboard_bulk_2026-07.parquet`: **1,531,094 rows x 69 columns**, 64.0MB zstd
(41.8 bytes/row), base month 2026-07-01, scores from run `refactor_growthfix`, join key
`CompanyNumber` as plain string equality, already 8-char zero-padded on both sides. Five blocks
left-joined outwards from the Companies House panel: CH base, charges and debt, filing compliance
and change events, the LBG and competitor block, and the four model scores.

Three things the doc leads with, because each is easy to misread:

1. **7.96% of rows have no scores and that is correct, not a missing file.** Scores exist only where
   `CompanyStatus` is exactly `Active`, 1,409,284 of 1,531,094.
2. **The contract columns are as at 2026-05-01, not July**, deliberately. Find a Tender's feed ends
   5 June 2026, so June and July coverage is partial and would make companies look like they stopped
   winning work. They are display-only and did not feed the scores. Stale but structurally correct
   beats current but biased.
3. **`sector IS NOT NULL` recovers the widened universe** from the file, so no second extract is
   needed.

And one convention that runs through the sparse blocks: **counts and flags coalesce to 0 or false,
but `months_since_*` columns stay NULL.** No row means "never", and a zero there would read as "this
month", which is the opposite of the truth. That is why those columns look 98% null, and that is the
correct shape rather than missing data.

The doc explicitly replaces `reports/shap_feature_catalog.md` for handover purposes, which had gone
stale.

**Why it matters for the report:** this is where the structured half stopped being a modelling
exercise and became a product input. The universe number the dashboard uses, 1,531,094, enters the
project here.

## Stream J. Samuel's three-source dashboard pack (Samuel, 11 to 13 August)

**Branches:** `samuel/spine-crosswalk` (`b18434e`) and `vishal-samuel/harmonisation` (`cfa2281`,
`458969f`). **Notebooks:** `08_land_registry_property_signals` (rewritten), `10_ukri_grants_signals`,
`30_property_dashboard_export`, `31_news_shortlist`, `32_hiring_adzuna`. **Scripts:**
`build_grants_pack.py`, `build_trademark_pack.py`, `harvest_ukri_orgs.py`, `src/dashboard_export.py`.
**Docs:** `reports/dashboard-pack.md`, `reports/adzuna-limitation.md`.

Three sources matched to the 1,493,972-company universe, each shipping the same three files as the
Gazette work (`<source>_events.csv`, `<source>_company_features.csv`, `<source>_signals.csv`), with
the agreed event columns `CompanyNumber, event_date, event_type, detail, value, url, confidence,
match_method`.

| Source | Companies | Share | Events | Match |
|---|---|---|---|---|
| Land Registry property | **60,629** | 4.06% | 318,068 | company number |
| IPO trade marks | **15,713** | 1.05% | 93,795 | name + postcode area |
| UKRI grants | **10,254** | 0.69% | none | name + postcode |
| Guardian news | **0** | 0.00% | none | name + corroboration |
| Adzuna hiring | not collected | | | see below |
| **Any of the three that worked** | **78,782** | **5.27%** | | |

773 companies carry all three, 6,268 carry two. For comparison the Gazette layer reaches 19,814
companies, 1.33%, so these three together reach four times as many. That is worth stating in the
report next to N5: the statutory-record finding is about the Gazette specifically, not about
structured public sources in general, and property in particular reaches four times as far.

**The three vintages, which are not the same, and this is the point of the pack.** Land Registry runs
to 2026-06-29 (the CCOD file); UKRI to 2026-08-11 (the day the API was harvested, no history exists);
IPO trade marks to **2018-01-28**, which is not a lag but a hard stop. The Intellectual Property
Office published its free bulk extract on 13 February 2018 and has never updated it. There is no
newer free file, and it is checkable on the gov.uk page. Practical effects the pack spells out:
`tm_count_12m` is zero for every company, `tm_days_since_latest` averages 5,596 days, and the tile
must carry the vintage or a reader concludes the company stopped filing rather than that the source
stopped recording. What it can honestly say is that the firm was investing in a brand before 2018.

**Grants have no dates and never can.** `grant_has_date` is 0 on all 10,254 rows, because dates live
on UKRI project records and reading them would cost about 97,000 API calls. `regNumber` is in the API
schema but populated on **0 of 500** organisations sampled, so there is no number to join on. And
45.3% of UKRI organisations publish no postcode at all and were dropped rather than guessed at, which
means "no grant" here can mean "no match was possible", not "no funding". That is a weaker kind of
absence than the property one and the pack says so.

**Adzuna: an access failure and a finding, which must not be confused.** Every endpoint returned HTTP
401 `AUTH_FAIL`, uniformly across all three called and on the very first call of the session. Ruled
out by evidence rather than assumption: not a rate limit (that returns 429, never seen), not a
malformed request (the URL matched the documented shape), not a code fault (the same path worked in
July). Most likely cause: the credentials were rejected as a pair, and the `app_id` supplied measured
9 characters where Adzuna issues 8. That is an account problem, recoverable by anyone with a working
key, and the notebook runs end to end the moment authentication succeeds. **The finding is the
separate half**, already visible in July when access worked, and it is the one that belongs in
Limitations: the source is structurally mismatched to the question.

This closes the hiring source. It was removed from the dashboard rather than left as a permanently
empty tile promising something that would never arrive, which is the same discipline as the news
tile's three states.

## Stream K. Sneha's competitive market analysis (Sneha, 13 to 18 August)

**Branch:** `sneha/market-analysis`. **Notebook:** `notebooks/market_analysis.ipynb`, 27 cells.
**Outputs:** `mi_league_2026-07.csv`, `mi_lapsed_destinations_2026-07.csv`,
`mi_sector_borrowing_2026-07.csv`.

Run against the same July 2026 Parquet, so every number is directly comparable with the modelling
side. Eight sections: the market at a glance (sector, size, age), the lender league table, each
bank's strength by sector, market concentration, share of each client's borrowing that is ours, how
contested our book is, clients under pressure, and where lapsed clients went.

**The league table, and the reason it is a finding rather than a chart:** NatWest 18,235, HSBC
15,899, Barclays 11,974, **LBG 10,604**, then challenger banks 7,512, asset and invoice finance
6,312. Lloyds is fourth in SME secured lending in this universe. Note that this is a *company count
by main lender* on the widened universe and it is not the same cut as the 14b charge-level league
table in Stream G (NatWest 16.4%, LBG 12.1%, Barclays 12.0%, HSBC 11.9%), which is a share of
charge-lender rows. **The two agree on the ordering and disagree on the base, so cite one or the
other and say which.**

Concentration: HHI 0.133, top four hold 65.6%. Book quality: 73.3% of LBG clients are sole-banked,
11,733 current clients, **14,416 lapsed** splitting 5,860 who stopped borrowing entirely and 8,556
who now borrow from a rival. Median client age 6.3 years.

`sneha/base` was pruned on 13 August, and on 18 August the branch was reduced to the market-analysis
notebook alone. The earlier notebooks (`04_exiting_relationships`, `05_contract_finder`,
`06_director_changes`) are gone from that branch, but they survive on `sneha-viktor/shap` and are
already described in Stream D. **Cite Stream D from `sneha-viktor/shap`, not from `sneha/base`.**

*Later repurposed:* directly. This became the Analytics page of the dashboard, with the three CSVs
read where they sit rather than copied in, and the other eight figures recomputed with her own
expressions transcribed from the notebook, so the page shows the same measurement rather than a new
one. Every displayed figure is checked against her CSVs, against the notebook output, and against an
independent recomputation from the Parquet, and that check is part of the dashboard's regression
suite.

## Stream L. The dashboard rebuilt as a query server (Vishal, 10 to 24 August)

**Branch:** `vishal/dashboard`, three commits on 24 August (`d4071ff` the dashboard, `df4fd84` the
documentation, `8ebeef6` the extended Gazette notebooks). **This is the largest single delivery of
the fortnight: 49 files, ~21,500 lines added over `main`.**

**Full technical account: `drafts/dashboard-deep-dive-2026-08-25.md`.** What follows is only what the
report chapter needs.

| Date | What |
|---|---|
| 10-13 Aug | NB11 rebuilds the 52 Gazette features on notices through 31 July; NB12 joins them to the widened universe; NB13 joins them to Viktor's July Parquet |
| ~14 Aug | NB14 audits every news output on the project and writes the corrected signal file |
| 19 Aug | Adversarial verification pass against the live server, ~400 assertions, five defects |
| 21 Aug | `FILTER_SPEC.md` closes; presets made adjustable |
| 24 Aug | Everything committed, plus a 427-line handbook and an 864-line design document |

**The architecture changed twice and the current one is the third.** The plan was a signals table with
thin per-pipeline adapters. What was built first was a sharded browser store: a ~5MB `core.js`
holding the 105,078 signalled companies plus a bitmask of which sources each had, then per-source
shards keyed on the last two characters of the company number, injected as `<script>` tags on demand.
It worked and it was still wrong, because everything in it was a build artefact: the browser held a
second copy of the data that could drift, the 1.43M companies with no signal could not be filtered at
all because they were not in the store, and every new filter meant regenerating 100 shards.

**What exists now is DuckDB reading the Parquet in place.** `dashboard/serve.py`, 1,688 lines, is a
Flask app holding one in-memory DuckDB connection. No database file is created, nothing is
precomputed, the Parquet is never written to, and there is no cache anywhere except the Analytics
page. `dashboard/index.html`, 4,462 lines of dependency-free vanilla JS, fetches JSON from about a
dozen `/api/*` endpoints and builds DOM. The universe went from 105,078 to **1,531,094**, and the
line that matters for the report is the consequence rather than the change: *every count on screen is
measurable at runtime rather than baked at build time, so the dashboard cannot disagree with the
data, because there is no second copy to disagree with.*

The engine choice was measured, not assumed. DuckDB against PyArrow on this dataset: filtering and
name search are near ties (25ms vs 28ms, 52ms vs 65ms), and the decision came from aggregation 9x,
sorting 12x, startup 83x, and memory **0.2MB against 444MB**. Aggregation settled it, because a
single filter-panel repaint fires about 57 aggregate queries: every filter option carries a live
count. *(Caveat for the writer: this benchmark is in no repository file. It comes from Vishal's
working record via `dashboard_design.md` section 2, and the sharded build no longer exists on disk to
inspect.)*

**Six sources live, none pending:** Gazette, news, contracts, property, trade marks, grants. The
governing rule, and it is the one to quote: **anything on the spine can be filtered, anything in a
side table can only be shown on a profile.** 27 filters in six groups, nine presets, three views,
a company profile with a single cross-source timeline, and an Analytics page carrying Sneha's work.

**Three findings from this stream that belong in the report.**

**L1, ordering that is merely correct is not enough.** The Gazette and Former LBG views ordered on
non-unique keys with no tie-break, so DuckDB's parallel scan arranged ties differently on each run.
Measured: five identical calls to the LBG view returned **five different sets of companies**; walking
six pages of 100 showed **526 distinct companies in 600 slots, so 74 were never displayed at all**;
and on screen, growing the list from 25 to 50 moved 15 of the 25 visible rows. Fixed with one
constant appended to every ordered query, `ORDER BY ..., CompanyNumber ASC`. The lesson generalises
past this project: an ordering has to be *total*, or pagination quietly lies, and nothing on screen
indicates it.

**L2, filters that fail open are worse than filters that fail closed.** `gazette=not_a_state`,
`repayment=bogus`, `preset=not_a_preset` and `view=not_a_view` all silently dropped the filter and
returned all 1,531,094 rows, while `segment=NoSuchSegment` correctly returned 0. Same user error,
opposite outcomes, and the failure widened the result set. A typo that returns nothing is obvious; a
typo that returns everything looks like a working query.

**L3, the two-outstanding-measures investigation, which overturned the project's own conclusion.**
The file carries two "outstanding" measures that disagree: `Mortgages.NumMortOutstanding` (the CH
bulk count) and `n_charges_outstanding` (our charge-level lender pipeline). They differ on 2,859
companies, and on 1,300 one is zero while the other is not, producing **996 companies where the bulk
says nothing is outstanding but a named lender is attached**. Inside the "no incumbent to displace"
preset that left 661 companies with a lender, 118 of them current LBG clients. The first reading was
that this was a business error in the prospecting list. It was not. The disagreement is a function of
**company age**: 0.10% under 10 years, rising to **9.29% at 50 years plus**, a ninety-fold gradient.
Disputed LBG relationships carry an average charge age of **34.4 years** against 12.9 where the two
sources agree, 88 of 173 have no satisfaction record at all, and of the 118 current LBG clients only
**4 hold a charge under 10 years old**. That is the signature of charges left open on the register
because a satisfaction was never filed, not of live secured borrowing: our gate holds a charge open
whenever the satisfaction date is missing, which is exactly the condition expected on a 1980s charge.
Alternatives were ruled out (England and Wales disagrees more than Scotland or Northern Ireland, so
it is not jurisdictional; and the bulk is not clean either, its own three counts failing to reconcile
on 463 companies). The preset was left alone: the "fix" would have deleted 839 real prospects to
correct a phantom.

**This one is worth a full subsection in Critical Evaluation**, because it is the clearest example in
the project of provenance beating plausibility, and it also names a gap at source: **the lender block
carries no as-of date and no staleness flag**, unlike the Gazette and contracts blocks, so its
currency cannot be checked from the file at all.

**What was verified.** An adversarial pass on 19 August with ground truth written independently from
column semantics rather than copied from the implementation, roughly 400 assertions. The filtering
came through clean: 63 facet counts, 34 filter cases, nine presets decomposed into 36 conditions, 22
hand-built combinations including 8 deliberate contradictions, and 120 seeded random combinations,
with zero count mismatches and zero rows failing the predicate they were selected by. Every injection
attempt returned 0 rows. The presets were verified by **set difference in both directions rather than
by count**, because two predicates can agree on a total and still select different companies; eight
of nine return 0 and 0. All five defects it found were outside the filtering.

### Stream L, sub-thread: the news audit (NB14) and two retractions

`notebooks/14_news_signal_audit.ipynb` re-checked every news output the project produced against the
APIs that made them, and two of three needed correcting. This supersedes part of Stream E and the
report must use these verdicts:

| Output | Sample | Reported | Verdict |
|---|---|---|---|
| `nb08_spine_news_signals.csv` | 96 | 92 of 96 have coverage | **Not usable.** Query defect |
| `nb09_guardian_signals.csv` | 96 | 2 verified | **Stale.** Predates the verification hardening |
| `guardian_results.csv`, `gnews_results.csv`, NB07 NewsAPI | 72 | 2, 3 and 5 hits | Method sound, unverified, all hits are collisions |

The NB08 diagnosis is now precise rather than inferred: 96 companies produce only **six distinct
article counts, all bunched at 247 to 249**, and companies sharing a count share their sentiment
scores exactly. The chronology called this a broadcast or merge bug on 8 August; the audit identifies
it as a query defect, one query built per template rather than per company.

**The corrected headline, and it is stronger than what Stream E recorded:** across every API tried
(Guardian, GNews, NewsAPI, and GDELT which never ran because the IP was blocked) and across both
samples, **no company has verifiable, company-specific news coverage**. The dashboard's own second
run extends the sample: 467 companies searched in total, 96 from the stress-test grid plus 398 from
the model shortlist, of which 27 were not searchable and stay *unknown* rather than "searched and
clean". Zero verified. **N1 now rests on 467 companies rather than 96.**

*One discrepancy to resolve before publication.* NB14's audit table attributes `nb08_spine_news_
signals.csv` to **Viktor**; the commit that added `08_news_api_large_coverage.ipynb`
(`015363d`, 2 July) is authored by **vshal999**, and this chronology's Stream E credited Vishal.
Somebody should settle it rather than letting the report carry both.

## Stream M. The report draft (Viktor, with Sneha's sections, 8 to 25 August)

**Branch:** `main`. Fifteen commits since 8 August, all authored `Viklin41`.
`latex-report/lloyds-commercial-banking-intelligence-report-draft.tex`, **1,663 lines**.

| Date | What |
|---|---|
| 8 Aug | Draft plus Sneha's work imported; the new index plan |
| 10, 18 Aug | Chapter 2 draft, then Background and the structured-data sections, both Sneha |
| 21-22 Aug | Ch 3.2 drafted and finished, ch 3.4 started and finished |
| 23 Aug | Ch 3.5 drafted |
| 24 Aug | Ch 4.1 subsections, 4.1.4, then 4.1 finished; abstract, introduction and market analysis (Sneha) |
| 25 Aug | Sec 4.3 drafted |

Current skeleton: Introduction, Background, **Execution** (organisation and reorganisation, data
acquisition, structured feature engineering, targets and the leakage-safe split, the pipeline as
software, unstructured data, dashboard, engineering practice), and **Critical Evaluation** (modelling
design and results across eleven runs, the leakage defect, N4, verdicts by model family, global SHAP,
what the error bars are worth, why pooled precision@N is misleading, and the narrative-against-
statutory synthesis for N1 and N5).

Two structural notes for whoever finishes it. The chapter on the dashboard is currently two
subsections (`A Bankers View`, `Routing the shortlist by counterparty`) and predates Stream L
entirely, so it describes the superseded architecture. And section 3.4's `TBC` marker on "Leakage and
evaluation under time" is still open in Background.

## Stream N. SHAP figures and shortlist reasons (Viktor, 21 August)

**Branch:** `sneha-viktor/shap`, commit `d8b263f`. Four scripts, four figure pairs, four tables, four
reason files.

`scripts/make_shap_beeswarms.py` produces beeswarms for all four targets;
`make_shap_gate_ladder.py` produces the lending gate ladder (figure plus a 25-row CSV and a LaTeX
table); `make_shap_identity_receipt.py` produces a 17-row lender-identity receipt table, which is the
evidence artefact behind N4; and `make_shortlist_reasons.py` writes
`reports/shortlists/top100_<target>_2026-07_reasons.csv`, one reason string per company for all four
top-100 lists.

The reason files are the commercially useful output of this commit and they close a real gap: until
this point the shortlists were 398 company numbers with scores and nothing a relationship manager
could read. They also line up with the dashboard's own "why this company is in your list" panel, so
the two halves say the same thing in the same words.

*Figures are generated by script, not by notebook.* That is worth one line in Engineering practice:
every figure in the results chapter can be regenerated from a recorded run without opening a
notebook.

---

## The measured negatives, with their dates

These are the distinguishing contribution. Most student projects report what worked; these are
properly measured answers to questions the brief actually asked, and each one has a date and a
receipt.

| # | Finding | Evidence | Owner | First measured |
|---|---|---|---|---|
| N1 | **Narrative media does not reach SMEs** | Raw 2.8-6.9% across NewsAPI, Guardian, GNews; **0 of 467 verified** across two samples (96-company grid plus the 398 model shortlist), 0 of 83 articles in the first; Tesco control returns 1,209. Independently 0 of 100 on GDELT | Vishal, Viktor | 9 Jun (GDELT), 2 Jul (canonical), 14 Aug (audited and widened) |
| N2 | **Market-identifier data does not reach SMEs** | 0.10% LEI, **0.00% ticker** across 869,043 companies. Corrected down from 9.14%, an orphan-join artefact | Samuel | 25-26 Jun |
| N3 | **Losing a bank does not predict distress** | 7.2% of firms lost a bank in the 24 months before distress, against a 5.5% baseline | Samuel | 9-11 Jun |
| N4 | **Lender identity adds nothing a boosted model cannot already read** | At the most conservative gate (7d/3d) LightGBM gains nothing; any gain above it scales monotonically with gate looseness, and `insolvency` is the control that shows no gradient | Viktor | 7-8 Aug |
| N5 | **Statutory sources reach SMEs, but only after the fact** | The Gazette covers 106,664 companies, of which only **1,033 (0.075%)** are inside the 1.37M Active universe | Vishal | 26 Jul |

**A sixth, added 25 August. N6: statutory reach is source-specific, not uniform.** Samuel's three
packs reach 78,782 companies (5.27%) against the Gazette's 19,814 (1.33%), with Land Registry alone
at 60,629 (4.06%) on an exact company-number match. N5 is a finding about *the Gazette*, which only
publishes once something has gone wrong; it is not a finding about public structured data in
general. Property reaches four times as far and reaches companies that are still trading. State N5
and N6 together or N5 overclaims.

N1, N2 and N5 together justify the structured-first architecture. N3 and N4 justify the final model.
N6 keeps N5 honest.
The sharpest way to put N1 and N5 together is **narrative against statutory**: journalism ignores
small companies entirely, statutory registers cover them completely but only once something has
already gone wrong. That is a defensible thesis rather than a bare "unstructured data was useless",
and it explains every coverage number in the project.

---

## Cross-cutting issues surfaced by the crawl

1. **Notebook numbering collides across branches.** Sneha uses 04-06, Samuel uses 05-09, the news
   lab uses 04-10, and the modelling stream uses 10-19. Samuel flagged this himself in NB08/NB09.
   Anything merged to `main` needs renumbering, and the report should cite branch plus notebook
   rather than notebook alone.
2. **Contracts Finder was built three times** (Sneha NB05, Samuel NB06, and referenced again in the
   integration design). One of them has to be the canonical account in the report.
3. **Two sentiment methodologies** were developed and never reconciled: VADER/TextBlob on one
   branch, FinBERT on another.
4. **Three disagreeing master company lists** (869,043 spine / 1,372,321 feature matrix / 2,038,130
   panel). Settled above: they are nested, not contradictory.
5. **Committed API keys** in the news-lab notebooks. Rotation is a housekeeping item, not a report
   item, but it should be done before anything is shared or published. Still outstanding as of
   25 August.

*Added 25 August:*

6. **Four disagreeing universe counts now, not three.** 869,043 spine / 1,372,321 feature matrix /
   2,038,130 panel / **1,531,094 handover Parquet**. The fourth is the one the dashboard and the
   shipped scores use, and it is the July 2026 bulk across all statuses. They remain nested rather
   than contradictory, but the report must name which one each number is out of, every time.
7. **Two lender league tables that agree on order and disagree on base.** Stream G's is a share of
   558,693 charge-lender rows; Stream K's is a count of companies by main lender on the widened
   universe. Pick one per claim and say which.
8. **NB08's author is recorded two ways** (Stream L sub-thread). Settle it before publication.
9. **The report's dashboard section describes the superseded architecture.** Sections 3.7 and its
   subsections on `main` predate Stream L by two weeks. Rewrite from
   `drafts/dashboard-deep-dive-2026-08-25.md`.
10. **`sneha/base` no longer holds the notebooks it is cited for.** Cite Stream D from
    `sneha-viktor/shap`.
11. **`store_meta.json` is stale on `sources_live`**, listing three live and four pending. The server
    overrides it at runtime, so the screen is right, but the file should not be read as truth.
