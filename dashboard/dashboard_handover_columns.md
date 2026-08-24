# `dashboard_bulk_2026-07.parquet`: what is in the file and which card it feeds

**Viktor, 10 August 2026.** This ships with the parquet. It replaces
`reports/shap_feature_catalog.md` for this purpose, which has gone stale (see §8).

| | |
|---|---|
| File | `data/handover/dashboard_bulk_2026-07.parquet` |
| Built by | `notebooks/20_dashboard_handover.ipynb` |
| Rows | **1,531,094**, one per company, no duplicates |
| Columns | **69** |
| Size | **64.0 MB** zstd (41.8 bytes/row) |
| Base month | **2026-07-01** |
| Contract columns as-of | **2026-05-01** (deliberate, see §4) |
| Scores from run | `refactor_growthfix` |
| Join key | `CompanyNumber`, plain string equality, already 8-char zero-padded on both sides |

**The three things to read before wiring anything up.**

1. **7.96% of rows have no scores** and that is correct, not a missing file. See §6.
2. **The contract columns are as at 31 May 2026, not July.** They are for display only and did not
   feed the scores. See §4.
3. **`sector IS NOT NULL` recovers your own widened universe** from my file, so you do not need a
   second extract from me. See §2.

---

## 1. How to read this file at all

One row per company in my July 2026 panel. Five blocks left-joined outwards from the Companies
House panel, so a company that has no charges, has never won public work, or is not Active still
gets its row and simply carries nulls or zeros in the blocks that do not apply.

The sparse blocks (contracts, lender) follow one convention consistently, and it is worth knowing
because it is easy to misread:

- **Counts and flags coalesce to 0 or false.** No row means "none", so `contracts_won_12m = 0` for a
  company that has never bid for anything.
- **`months_since_*` columns stay NULL.** No row means "never", and a zero there would read as "this
  month", which is the opposite of the truth. So `months_since_last_award IS NULL` means never won,
  not won just now. This is why those columns look 98% null below; that is the correct shape, not
  missing data.

Null percentages throughout are over all 1,531,094 rows, including non-Active companies.

---

## 2. Block A, Companies House base (16 columns + 2 identity)

Straight from the monthly bulk download, as it survives into my panel.

| Column | Type | Null % | Meaning |
|---|---|---|---|
| `CompanyNumber` | VARCHAR | 0 | Join key, 8 chars, zero-padded |
| `base_month` | DATE | 0 | Always `2026-07-01`. The month this whole row describes |
| `source_date` | TIMESTAMP | 0 | Real extract date of the CH bulk file behind this row |
| `CompanyName` | VARCHAR | 0 | As registered |
| `CompanyStatus` | VARCHAR | 0 | Raw CH status, nine distinct values in this file |
| `is_active` | BOOLEAN | 0 | `CompanyStatus = 'Active'`. **Gates the scores** |
| `sector` | VARCHAR | 1.69 | Our target-sector label. NULL has a specific meaning, see below |
| `segment` | VARCHAR | 0 | Business segment label |
| `size_tier` | VARCHAR | 34.53 | Accounts-category size tier. Null where the company files nothing that reveals size |
| `tier_rank` | INTEGER | 34.53 | Numeric rank of `size_tier`, for ordering |
| `SICCode.SicText_1` | VARCHAR | 0 | Primary SIC, code and description in one string |
| `RegAddress.PostCode` | VARCHAR | 0.03 | Registered postcode. The only address field I carry |
| `company_age_years` | DOUBLE | 0 | Years since incorporation at the base month |
| `debt_ratio` | DOUBLE | 0 | Outstanding charges over total charges ever |
| `accounts_overdue` | BOOLEAN | 0 | Accounts past their due date at the base month |
| `Mortgages.NumMortCharges` | BIGINT | 0 | Total charges ever registered |
| `Mortgages.NumMortOutstanding` | BIGINT | 0 | Charges currently outstanding |
| `Mortgages.NumMortSatisfied` | BIGINT | 0 | Charges satisfied |

### `sector IS NULL` is not a defect, and it is how you recover your own universe

25,891 rows carry a NULL `sector`. Those are companies whose **July** SIC falls outside our target
sectors but which were in-sector in some other month. My universe is built by unioning every company
that matched a target SIC in *any* of the 33 months, and then emitting a row for it every month
whatever its current sector. That is deliberate: it stops a SIC recode from looking like a
dissolution in the time series.

You built your universe by applying the SIC map to one month's file, which is why our counts differ.
We reconciled this exactly on June: my slice filtered to `sector IS NOT NULL` gave 1,493,972 and
adding `is_active` gave 1,372,321, which were your two numbers to the row. **Zero companies in your
universe were missing from mine**, in either direction, so mine is a strict superset.

The July equivalents, straight off this file:

```sql
-- your widened universe
WHERE sector IS NOT NULL                 -- 1,505,203
-- your Trading bucket
WHERE sector IS NOT NULL AND is_active   -- 1,385,001
```

So filter, do not ask me for a second file.

### Lifecycle buckets

All nine statuses are in the file, so you can derive your four buckets from my column instead of
your CSV if you would rather have one source of truth:

| `CompanyStatus` | Rows |
|---|---|
| Active | 1,409,284 |
| Active - Proposal to Strike off | 97,721 |
| Liquidation | 22,779 |
| In Administration | 1,045 |
| Voluntary Arrangement | 116 |
| In Administration/Administrative Receiver | 87 |
| Live but Receiver Manager on at least one charge | 58 |
| In Administration/Receiver Manager | 2 |
| RECEIVERSHIP | 2 |

---

## 3. Block B, panel deltas (25 columns)

Month-over-month movement, computed in `notebooks/13_panel_deltas.ipynb` against a 33-month spine.
These are the columns that carry most of the models' signal.

| Column | Type | Null % | Meaning |
|---|---|---|---|
| `d_charges_3m` | BIGINT | 3.65 | Change in total charges over 3 months |
| `d_charges_6m` | BIGINT | 7.28 | Same over 6 months |
| `d_charges_12m` | BIGINT | 13.95 | Same over 12 months |
| `d_outstanding_3m` | BIGINT | 3.65 | Change in outstanding charges, 3 months |
| `d_outstanding_6m` | BIGINT | 7.28 | Same, 6 months |
| `d_outstanding_12m` | BIGINT | 13.95 | Same, 12 months |
| `d_satisfied_12m` | BIGINT | 13.95 | Change in satisfied charges, 12 months |
| `debt_ratio_trend_12m` | DOUBLE | 13.95 | Movement in `debt_ratio` over 12 months |
| `new_charge_events_12m` | DOUBLE | 0 | Count of new-charge events in the last 12 months |
| `months_since_last_new_charge` | BIGINT | 97.97 | NULL means never took a charge |
| `status_changed` | BOOLEAN | 1.20 | Status differs from last month |
| `months_in_current_status` | BIGINT | 0 | How long in the current status |
| `ever_distressed_before` | BOOLEAN | 0 | Has previously been in a distress status |
| `segment_upgraded_12m` | BOOLEAN | 41.40 | Moved up a segment in 12 months |
| `segment_downgraded_12m` | BOOLEAN | 41.40 | Moved down a segment in 12 months |
| `months_since_segment_change` | BIGINT | 0 | Months since the last segment move |
| `accounts_overdue_streak_months` | BIGINT | 0 | Consecutive months with accounts overdue |
| `accounts_stale_streak_months` | BIGINT | 0 | Consecutive months without a filing |
| `confstmt_late` | BOOLEAN | 0 | Confirmation statement is late |
| `days_to_next_accounts_due` | BIGINT | 0.07 | Days until the next accounts deadline, negative if passed |
| `months_since_last_accounts_filing` | BIGINT | 22.08 | NULL means never filed accounts |
| `months_since_last_confstmt` | BIGINT | 15.76 | NULL means never filed a confirmation statement |
| `sic_changed_12m` | BOOLEAN | 13.95 | Changed SIC in 12 months |
| `name_changed_12m` | BOOLEAN | 13.95 | Changed name in 12 months |
| `postcode_changed_12m` | BOOLEAN | 13.95 | Changed registered postcode in 12 months |

**The 13.95% null rate on the 12-month deltas is normal**, and it is companies incorporated less
than twelve months ago, which have no twelve-month history to compare against. The 41.40% on the
segment flags is the same effect plus companies with no segment to move between.

**Worth knowing why this file is July and not June.** These same nine 12-month columns come back
**100% NULL** at a June 2026 origin, because Companies House never published a June 2025 snapshot
and every twelve-month lag from June 2026 lands on that hole. That is not recoverable, I re-probed
the CH server and the file has never existed. It is the reason we moved the dashboard to July.
Notebook 20 asserts these columns are alive, so the file cannot silently ship with them dead.

---

## 4. Block C, contract features (7 columns + 2 provenance)

Public procurement awards from Contracts Finder and Find a Tender, matched to CH numbers in
`14_contracts_asof.ipynb` and `14a_name_matching.ipynb`.

**These are as at 31 May 2026, not July, and they did not feed the model scores.**

| Column | Type | Null % | Meaning |
|---|---|---|---|
| `contracts_won_12m` | BIGINT | 0 | Distinct contracting processes won in the trailing 12 months |
| `total_value_won_12m` | DOUBLE | 0 | Summed award value share, GBP |
| `awards_with_value_12m` | BIGINT | 0 | How many of those awards carried a value at all |
| `months_since_last_award` | BIGINT | 98.99 | **NULL means never won**, not "won long ago" |
| `d_contracts_12m` | BIGINT | 0 | This 12 months against the previous 12 |
| `ever_won_contract` | BOOLEAN | 0 | Has ever appeared as a supplier |
| `first_award_in_12m` | BOOLEAN | 0 | First ever award fell in the last 12 months |
| `contracts_asof_month` | DATE | 0 | Always `2026-05-01`. The vintage of this block |
| `contracts_stale` | BOOLEAN | 0 | Always `TRUE`. Flag for the UI |

**15,517 of the 1,531,094 companies have ever won a public contract**, about 1%. This block is
sparse by nature and a card built on it will be empty for almost everybody. That is real, not a
matching failure.

### Why May and not July

The as-of table includes awards published up to the **end** of the snapshot month. Find a Tender's
feed ends **5 June 2026** and Contracts Finder's ends 3 July, so:

| Partition | Needs data through | Verdict |
|---|---|---|
| **2026-05-01** | 31 May | **complete** |
| 2026-06-01 | 30 June | censored |
| 2026-07-01 | 31 July | heavily censored |

The monthly flow makes it obvious. Distinct CH-linked companies winning a contract: 3,362 in May,
1,203 in June, 191 in July. Procurement did not collapse, our observation of it did.

Censored contract features are not merely noisy, they are biased one way: they make companies look
like they **stopped winning work**, which is exactly the wrong signal to put in front of a
relationship manager. Two months stale but structurally correct beats current but systematically
understated.

**Suggested wording for the tile:** *"Contract activity shown as at 31 May 2026. Later coverage is
incomplete."*

### The one deliberate inconsistency in this file

The scores were computed from **July's own** contract features, which are censored. These columns
are May's. That mismatch is intentional and should not be "fixed":

- Contract features are between **0.2% and 1.0%** of any of the four models' total SHAP mass, so
  recomputing the scores against May would move almost nothing.
- Rescoring would break agreement with the July shortlists already circulated.

Notebook 20 asserts the two months differ, so anyone who swaps in the July contract partition will
trip a failing cell that explains why.

---

## 5. Block D, lender features (12 columns + 1 label)

Who a company banks with for secured lending, from the Charges API harvest in
`14b_lender_charges.ipynb`. **Descriptive only: none of these fed any score** (see §6).

| Column | Type | Null % | Meaning |
|---|---|---|---|
| `n_charges_outstanding` | BIGINT | 0 | Outstanding charges, from the charge register |
| `n_lbg_charges_outstanding` | BIGINT | 0 | Of those, held by an LBG entity |
| `is_lbg_client` | BOOLEAN | 0 | Currently has an outstanding LBG charge |
| `ever_lbg_client` | BOOLEAN | 0 | Has ever had one |
| `lbg_share_of_outstanding` | DOUBLE | 93.24 | LBG share of outstanding charges. NULL where nothing is outstanding |
| `n_distinct_lenders` | BIGINT | 0 | Distinct lender groups on outstanding charges |
| `n_competitor_lenders` | BIGINT | 0 | Of those, not LBG |
| `months_since_last_lbg_charge_created` | BIGINT | 98.29 | NULL means never |
| `months_since_last_lbg_satisfaction` | BIGINT | 98.86 | NULL means never. **The lapsed-client signal** |
| `competitor_entered_12m` | BOOLEAN | 0 | A competitor took a new charge in 12 months |
| `lbg_charge_satisfied_6m` | BOOLEAN | 0 | An LBG charge was satisfied in 6 months |
| `competitor_charge_created_6m` | BOOLEAN | 0 | A competitor charge created in 6 months |
| `primary_lender_group` | VARCHAR | 94.35 | Largest lender by outstanding charges |

103,539 companies have at least one outstanding charge. 11,733 are current LBG clients and **14,416
are lapsed** (`ever_lbg_client AND NOT is_lbg_client`), which is the most directly actionable
segment in the whole file.

Top `primary_lender_group` values: natwest 18,235, hsbc 15,899, barclays 11,974, lbg 10,604,
challenger_bank 7,512, asset_invoice_finance 6,312, other_bank 5,030, trustee_spv 4,710.

**A note on which lender panel this is.** There are six variants on disk. This file uses
`lender_panel_calib`, which gates a charge on `visible_on(4d)` and `satisfied_on + 1d` against the
real extract date. The module default, `lender_panel`, gates on `created_on` against the nominal 1st
of the month and **leaks**: notebook 14b's rewritten leakage test exists specifically to fail
against it. If you ever rebuild this yourself, use `_calib`.

---

## 6. Block E, model scores (4 columns)

| Column | Type | Null % | Horizon from 1 July 2026 | Positive event |
|---|---|---|---|---|
| `score_lending` | DOUBLE | 7.96 | Aug to Oct 2026 (3m) | Registers a new charge, i.e. takes on new secured borrowing |
| `score_insolvency` | DOUBLE | 7.96 | Aug 2026 to Jan 2027 (6m) | A genuine insolvency event, not a benign strike-off |
| `score_voluntary_exit` | DOUBLE | 7.96 | Aug 2026 to Jan 2027 (6m) | A strike-off proposal appears, whether or not later withdrawn |
| `score_growth` | DOUBLE | 7.96 | Aug 2026 to Jul 2027 (12m) | Moves up a size tier on its accounts category |

### The nulls are correct behaviour

Scores are present on exactly the 1,409,284 Active companies and absent on the other 121,810.
Notebook 20 asserts that set equality. The models are fitted on trading companies, and the live
scoring path filters on `is_active`.

Because your population is Gazette-matched, and a company with a winding-up petition is on its way
out of Active status, **a large share of the companies on your screen will have empty score cards**.
That is right. A lending-readiness forecast for a company already in liquidation is a number with
nothing behind it. Please render the reason rather than a zero:

> *"Not scored: company is no longer Active. The lending, growth and exit models are fitted on
> trading companies only."*

### These are forecasts, and how to say so

The models were trained on 33 months of history where features at month `t` predict outcomes
strictly in `t+1 .. t+H`. Nothing from the outcome window is visible to the model. On historical
months we can check the answer, and that is where the numbers below come from. For July 2026 the
window has not closed, so **the July scores cannot be validated on July**; their credibility comes
entirely from the held-out historical origins.

| Card | Base rate | Hit rate in the top 100 | Lift |
|---|---|---|---|
| Lending Readiness | 0.26% and 0.28% | 0.43 and 0.41 | ~160x |
| Credit Risk Exposure | 0.33% | 0.16 and 0.14 | ~45x |
| Voluntary Exit | 8.2% and 7.2% | 0.85 and 0.78 | ~10x |
| Growth Signal | 2.1% | 0.22 | ~10x |

**Do not render the raw score as a probability.** The top lending scores run around 0.577 while the
observed hit rate in that band is 0.43. The recalibration undoes the 10:1 negative downsampling but
is a prior correction, not a curve fitted against observed outcomes, and no reliability check was
recorded for any run. So the raw number runs optimistic exactly where the dashboard looks.

**Use the score to sort, and the measured hit rate to describe.** Show rank or decile plus the hit
rate for that band. If you do show the raw number, label it "model score", not "probability". The
sentence that works with a non-technical audience:

> "This company is in our top 100 for new borrowing over the next three months. When we tested this
> model on months where we already knew the answer, 43 of every 100 companies it ranked this highly
> went on to borrow within three months. The background rate is about 3 in 1,000, so the list is
> roughly 160 times better than picking companies at random."

**Two more UI rules.** The horizons differ, so never render the four side by side without their
windows: a Growth number is about the next year, a Lending number about the next quarter. And
**`score_voluntary_exit` should not drive a ranked list**: 982 of its top 1000 values are exact
ties, so the ordering inside that band is arbitrary. Show the tied band or leave it out of rankings.

**No lender feature fed any of these scores.** The run tag `refactor_growthfix` was configured with
no lender block, which is why the lender columns are labelled descriptive throughout. Keeping those
two things apart is what stops the leakage argument from ever reaching the dashboard.

---

## 7. Column-to-card mapping

### Satisfiable now

| Card / element in `index.html` | Columns |
|---|---|
| **Model indices panel** (the four "awaiting file" rows) | `score_lending`, `score_insolvency`, `score_voluntary_exit`, `score_growth`, gated on `is_active` |
| **Contracts source tile** | `ever_won_contract`, `contracts_won_12m`, `total_value_won_12m`, `awards_with_value_12m`, `months_since_last_award`, `first_award_in_12m` |
| **Lifecycle chips and filters** | `CompanyStatus`, `is_active` |
| **Watchlist row meta** (`sector · segment`) | `sector`, `segment`, plus `size_tier` / `tier_rank` for a size chip |
| **Hero identikit**, all but incorporation date and full address | `CompanyName`, `CompanyNumber`, `CompanyStatus`, `sector`, `segment`, `RegAddress.PostCode`, `company_age_years` |
| **New card worth adding: Lender relationship** | `is_lbg_client`, `ever_lbg_client`, `primary_lender_group`, `n_competitor_lenders`, `months_since_last_lbg_satisfaction`, `competitor_charge_created_6m` |
| **New card worth adding: Borrowing profile** | `Mortgages.NumMortCharges`, `Mortgages.NumMortOutstanding`, `debt_ratio`, `d_charges_3m`, `d_charges_6m`, `new_charge_events_12m`, `months_since_last_new_charge` |
| **New card worth adding: Filing health** | `accounts_overdue`, `accounts_overdue_streak_months`, `accounts_stale_streak_months`, `confstmt_late`, `days_to_next_accounts_due`, `months_since_last_accounts_filing`, `months_since_last_confstmt` |

The lapsed-LBG segment (`ever_lbg_client AND NOT is_lbg_client`, 14,416 companies) is the one I
would put a filter chip on. It is the clearest "call this company" signal in the file.

### Partly satisfiable

| Card | What works | What is missing |
|---|---|---|
| **Hero identikit** | everything above | `IncorporationDate` and full address. I carry `company_age_years` and the postcode only. Keep using your universe CSV for those, or ask and I will widen the panel |
| **Timeline, "every source, one column"** | contracts can contribute one entry per company via `months_since_last_award`, resolved to a month | My blocks are **monthly aggregates, not dated events**. A charge registered on 14 June appears here as a count going up, with no date and no document. Dated events exist upstream in `charges_flat.parquet` and `contracts_flat.parquet`; an event feed is a separate small extract |
| **Landing hero stats** | universe-wide counts: companies scored, top-decile counts per index, companies with an LBG relationship | your four current tiles are Gazette counts. New tiles are a design decision, not a data one |

### Not satisfiable

| Card | Why |
|---|---|
| **News, Hiring, Property, Trade marks, Grants tiles** | Nothing in my pipeline touches these. Sam and Vishal's unstructured work is the route to News |
| **Evidence panel** (linkable documents) | The as-of tables carry no notice IDs or URLs. Award OCIDs exist in `contracts_flat.parquet` and charge document links in the Charges API harvest, neither in this file |
| **Gazette assessment panel** | Entirely your block, I have no Gazette data |
| **Per-company "why this score" drivers** | Only global SHAP importance exists today, about 40 rows per target, which is a statement about the model rather than about a company. Per-company drivers are computable via LightGBM `pred_contrib` and are the obvious fast follow, but they are not in this handover |

---

## 8. Do not use `reports/shap_feature_catalog.md`

It is a different lineage and it has gone stale. Specifically:

- **33 of the 41 model features are not in it at all.** Only 8 catalogue variables feed a model
  (three mortgage counts, `company_age_years`, `debt_ratio`, `accounts_overdue`, `sector`,
  `segment`). It predates notebooks 12 to 14.
- Its population is 1,372,321 Active-only, not the widened universe in this file.
- Its whole Layer-3 API block is superseded or dead: 8 contract fields replaced by block C here, 5
  lender-API fields replaced by block D, and 10 officers/filing/charges API fields with **no
  successor**, because they only ever covered about 0.01% of companies.
- The growth model dropped 14 columns after the NB18 defect (41 features down to 27). All 14 are
  still columns in this file, they simply do not feed `score_growth`.

Use this document instead.
