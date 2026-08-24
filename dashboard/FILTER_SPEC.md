# Global Filter System — Final Implementation Specification

**Status: BUILT AND VERIFIED LIVE. Last updated 21 August 2026.** Implemented in
`dashboard/serve.py` (DuckDB over the parquet) and rendered by `dashboard/index.html`. Section 8
records the original verification run and every deviation from the text below; Section 9 the
adversarial pass and the five defects it found; **Section 10 the presets becoming visible and
adjustable, which closed the last substantive deviation.** The three decisions in Section 7 have
been taken. *(This header previously read "awaiting approval, no code written". That was true when
the spec was drafted on 18 August and stale within a day.)*

All figures re-measured against `data/processed/dashboard_bulk_gazette_2026-07.parquet`
(1,531,094 rows × 124 columns) on 18 August 2026. Every number below was verified in this final
pass, not carried over from earlier analysis. All of them were then re-confirmed against the
running server on 19 August, see Section 8.2.

---

## 0. Two findings from the final verification

The redundancy test flagged two presets that are effectively single filters in disguise.

| Preset | Population | Closest single filter | Retains |
|---|---|---|---|
| **F Won public work recently** | 5,491 | Won in 12m (5,871) | **93.5% — repackaging** |
| **B Best prospects we don't bank** | 11,026 | Lending top 1% (14,093) | **78.2% — borderline** |

**F as specified adds almost nothing.** `awards_with_value_12m>0` removes only 380 of 5,871
companies. Reformulation tested and recommended below.

All other presets pass comfortably: A 26.8%, H 28.6%, D 8.8%, G 50.4%, C 9.4%, I 3.6%, E2 32.2%.

**Redundancy rule adopted:** a preset earns its slot only if it retains **under ~80%** of the
population of its most restrictive single-filter component. Otherwise it is a filter, not a preset.

---

## 1. Views

| View | Predicate | Population | Default ranking |
|---|---|---|---|
| **All Companies** | none | **1,531,094** | CompanyName |
| **Gazette Signal** | `gaz_matched = 1` | **19,525** | distress stage desc, latest notice desc |
| **Former LBG Client** | `ever_lbg_client AND NOT is_lbg_client` | **14,416** | months since LBG charge satisfied asc |

Views set the starting population. Filters narrow the currently selected view. All Companies applies
no predicate — the full universe, nothing removed.

---

## 2. Final filter taxonomy

### 2.1 Core

| Label | Column(s) | Meaning | Type | Population / values | NULL | "Not stated" | Redundant? | Caveat for UI |
|---|---|---|---|---|---|---|---|---|
| Segment | `segment` | Size/activity band from accounts category | categorical, 8 | 1,531,090 | 4 | no | no | — |
| Status | `CompanyStatus` | Raw Companies House status | categorical, 9 | 1,531,094 | 0 | no | no | **not built**, see decision 3 |
| Lifecycle | derived from `CompanyStatus` | Trading / Fading / Distressed / Insolvent | categorical, 4 | 1,531,094 | 0 | no | rollup of Status | offer one or the other, not both at once. **Lifecycle won**: Trading 1,409,284 · Fading 97,721 · Insolvent 23,915 · Distressed 174 |
| Region | `RegAddress.PostCode` (leading letters) | Postcode area | categorical, 175 | 1,530,591 | 503 | no | no | — |
| Industry | `SICCode.SicText_1` | Primary SIC code and description | categorical, 727 | 1,531,094 | 0 | no | no | needs type-ahead, not a dropdown |
| Sector | `sector` | Our 3 target sector groups | categorical, 3 | 1,505,203 | **25,891** | **yes** | **no — see below** | NULL means "SIC outside target sectors this month" |
| Company age | `company_age_years` | Years since incorporation | numeric range | 1,531,094 | 0 | no | no | — |

**Sector is not redundant with Industry.** Verified: of 610 distinct `SICCode.SicText_1` values,
**271 map to more than one sector**. Sector was assigned across `SicText_1–4`, but the parquet holds
only `SicText_1`, so sector carries signal from SIC 2–4 that we otherwise cannot see.

**`size_tier` is excluded.** Identical counts to `segment` for every non-null value; it is `segment`
with four categories blanked (34.5% null). Pure redundancy.

### 2.2 Borrowing

| Label | Column(s) | Meaning | Type | Population | NULL | "Not stated" | Caveat |
|---|---|---|---|---|---|---|---|
| Ever borrowed | `Mortgages.NumMortCharges` | Has ever registered a charge | boolean | 143,279 | 0 | no | — |
| Outstanding mortgages | `Mortgages.NumMortOutstanding` | Charges currently outstanding | numeric range | 102,273 (>0) | 0 | no | 93.3% are 0; do not default the slider to 0 |
| Repayment state | `debt_ratio` | Outstanding ÷ all charges ever | categorical | fully repaid 41,007 · partial 41,487 · all outstanding 60,785 | 0 | no | only meaningful where charges > 0 |
| New charge in 12m | `new_charge_events_12m` | Took new secured borrowing | boolean | 14,142 | 0 | no | — |

**Outstanding mortgage bands:** 0 → 1,428,821 · 1 → 59,276 · 2–5 → 39,245 · 6–20 → 3,524 · >20 → 228

### 2.3 Lender & Relationship

| Label | Column(s) | Meaning | Type | Population | NULL | "Not stated" | Caveat |
|---|---|---|---|---|---|---|---|
| LBG relationship | `is_lbg_client`, `ever_lbg_client` | Current / former / never | categorical, 3 | current 11,733 · former 14,416 | 0 | no | — |
| Main lender | `primary_lender_group` | Largest lender by outstanding charges | categorical, 13 | 86,468 | **1,444,626 (94.4%)** | **yes — critical** | must state it covers only 86,468; NULL means "no outstanding charge", not "no bank" |
| **Number of lenders** | `n_distinct_lenders` | Distinct lender groups on outstanding charges | numeric | 1 → 77,321 · 2 → 8,203 · 3+ → 920 | 0 | no | **new** — replaces the rejected "Sole lender" preset |
| Competitor lender present | `n_competitor_lenders` | Has a non-LBG lender | boolean | 76,949 | 0 | no | — |
| Competitor charge created (6m) | `competitor_charge_created_6m` | **General competitor activity** | boolean | **4,944** | 0 | no | 12% are ever-LBG — this is market-wide |
| Competitor entered an LBG relationship (12m) | `competitor_entered_12m` | **Rival arrived on an LBG client's register** | boolean | **230** | 0 | no | **100% are ever-LBG** — never label as "12-month version" of the above |

**Competitor fields reconfirmed this pass:** `created_6m` = 4,944, of which 613 (12%) ever LBG.
`entered_12m` = 230, of which **230 (100%)** ever LBG. The two measure different concepts, not
different time windows. Labels must never be "6m / 12m".

**Main lender values:** natwest 18,235 · hsbc 15,899 · barclays 11,974 · lbg 10,604 ·
challenger_bank 7,512 · asset_invoice_finance 6,312 · other_bank 5,030 · trustee_spv 4,710 ·
virgin_money 2,224

### 2.4 Filing

| Label | Column(s) | Meaning | Type | Population | NULL | "Not stated" | Caveat |
|---|---|---|---|---|---|---|---|
| Accounts overdue | `accounts_overdue` | Past the accounts deadline | boolean | 99,721 | 0 | no | — |
| Overdue 6+ months | `accounts_overdue_streak_months` | Consecutive months overdue | numeric | 66,985 | 0 | no | — |
| Confirmation statement late | `confstmt_late` | Statement overdue | boolean | 159,941 | 8 | no | — |
| No filing 24+ months | `accounts_stale_streak_months` | Consecutive months without any filing | numeric | 42,909 | 0 | no | — |

### 2.5 Momentum

| Label | Column(s) | Meaning | Type | Population | NULL | "Not stated" | Caveat |
|---|---|---|---|---|---|---|---|
| Size tier moved | `segment_upgraded_12m`, `segment_downgraded_12m` | Moved up/down a size tier | categorical, 3 | up 19,003 · down 22,071 | **633,803 (41.4%)** | **yes** | NULL = no 12m history or no segment to move |
| Relocated in 12m | `postcode_changed_12m` | Registered address changed | boolean | 154,597 | **213,566 (13.9%)** | **yes** | NULL = incorporated under 12 months ago |
| Industry changed 12m | `sic_changed_12m` | Primary SIC changed | boolean | 40,266 | **213,566 (13.9%)** | **yes** | same |

### 2.6 Signals

| Label | Column(s) | Meaning | Type | Population | NULL | "Not stated" | Caveat |
|---|---|---|---|---|---|---|---|
| Lending readiness | `score_lending` | Model score, 3-month horizon | band | top 1% 14,093 · top 10% 140,932 | **121,810 (8.0%)** | **yes** | band only; never "probability"; horizon must show |
| Growth | `score_growth` | Model score, 12-month horizon | band | top 10% 140,929 | 121,810 | yes | same |
| Credit risk | `score_insolvency` | Model score, 6-month horizon | band | top 1% 14,093 | 121,810 | yes | same |
| Gazette | see §4 | Named Gazette states | categorical | see §4 | 0 | no | never a bare "Gazette" toggle |

**Voluntary exit score is deliberately absent.** 998 of its top 1,000 values are exact ties and the
top-100 cutoff is shared by 139 companies. It cannot support a ranked or banded filter.

### 2.7 NULL handling rule

**A missing value is never treated as a negative.** Every filter with NULLs offers three states —
**Yes / No / Not stated** — where "No" means *observed false*, not *unknown*.

Critical cases: Momentum (13.9–41.4% NULL — companies too young to have history), Main lender (94.4%
NULL — means "no outstanding charge", not "unbanked"), Scores (8.0% NULL — not Active).

---

## 3. Final presets

Trading segments = `segment IN ('Micro','Small','Medium','Large')`, which excludes Dormant,
No Filings, Subsidiary and Unknown.

| # | Preset | Conditions | Population | Restriction | Retains |
|---|---|---|---|---|---|
| **A** | Proven borrower, no incumbent | `Mortgages.NumMortCharges>0 AND Mortgages.NumMortOutstanding=0` | **31,002** | Active + trading | 26.8% |
| **H** | Established, unlevered, high growth | `company_age_years>=5 AND Mortgages.NumMortCharges=0 AND score_growth>=p90` | **31,012** | Active + trading | 28.6% |
| **B** | Best prospects we don't bank | `score_lending>=p99 AND NOT ever_lbg_client AND trading` | **8,992** | Active + trading | 63.8% |
| **D** | Secured exposure deteriorating | `Mortgages.NumMortOutstanding>0 AND accounts_overdue_streak_months>=6` | **5,916** | **none** | 8.8% |
| **E2** | Growing and borrowing | `new_charge_events_12m>0 AND score_growth>=p90` | **3,609** | Active + trading | 32.2% |
| **G** | Silent distress, no Gazette yet | `gaz_matched=0 AND accounts_overdue_streak_months>=6 AND confstmt_late` | **2,520** | Active | 50.4% |
| **F2** | Contract winner with no borrowing | `contracts_won_12m>0 AND Mortgages.NumMortCharges=0` | **2,303** | Active + trading | 39.2% |
| **C** | Lapsed client, rival moved in | `ever_lbg_client AND NOT is_lbg_client AND competitor_charge_created_6m` | **467** | **none** | 9.4% |
| **I** | High credit risk on our security | `score_insolvency>=p99 AND n_lbg_charges_outstanding>0` | **401** | Active | 3.6% |

### 3.1 Changes made in this final pass

**F reformulated → F2.** As specified it retained 93.5% of "Won in 12m" and was a repackaging. Tested
alternatives: never borrowed 2,303 (39.2%) · no outstanding borrowing 3,234 (55.1%) · first ever
award 2,160 (36.8%). **Recommended: "Contract winner with no borrowing" (2,303).** The business
logic is stronger too — a company that has just won public work and has never borrowed is the one
with a genuine new financing need.

**B tightened.** At 78.2% it was borderline. Adding the trading-segment restriction brings it to
**8,992 (63.8%)** and aligns it with the other prospecting presets. A stricter variant exists —
"no lender on the register at all" at 2,500 (17.7%) — available if you want a sharper list.

### 3.2 Business interpretation

| Preset | Interpretation |
|---|---|
| A | Borrowed before and cleared it. No incumbent to displace. |
| H | Five years trading, never borrowed, top 10% growth. Untapped. |
| B | Top 1% for new borrowing, never an LBG client. |
| D | Security is held and the company has stopped filing on time. |
| E2 | Expanding and actively taking on secured debt. |
| G | Both filing signals failed but nothing has reached the Gazette. Earliest warning available. |
| F2 | Just won public work, has never borrowed — delivery needs working capital. |
| C | Left us, and a competitor has taken a charge within 6 months. |
| I | Top 1% insolvency risk where LBG holds an outstanding charge. |

### 3.3 Restriction rationale

**A and H must be trading-only.** `is_active` is a *status*; `Dormant` is a *segment*, and 89.4% of
Dormant companies hold Active status, so `is_active` alone does not exclude them. Verified for A:
37,375 as specified → 31,003 trading-only. Subsidiary is also excluded — a subsidiary's borrowing is
a group decision.

Also confirmed in this pass: **`primary_lender_group IS NULL` was doing no work in A.** It is derived
from outstanding charges, so when `debt_ratio = 0` it is null by construction (0 of 1,427,555
companies with no outstanding charges carry a lender). Removed.

> **This claim is wrong, and sections 9.5 and 9.6 explain why.** It is left in place because it is the
> reasoning that removed a condition from preset A and the correction has to be traceable to it.
> The figure 1,427,555 is reproducible only from **`n_charges_outstanding = 0`**, and against that
> column 0 companies do carry a lender. But preset A never tested that column: it tested
> `debt_ratio`, which is derived from the bulk `Mortgages.*` counts. Against
> `Mortgages.NumMortOutstanding = 0` the answer is **996 companies carrying a named lender**, not 0.
> The verification and the predicate used two different columns.

**C and D are deliberately unrestricted.** A deteriorating exposure or a lapsed client entering
administration is *more* urgent, not less. Restricting them would hide the cases that matter most.

---

## 4. Gazette

### 4.1 Recorded temporal decision

| | |
|---|---|
| Companies House snapshot | **1 July 2026** (`base_month`, `source_date`) |
| Gazette enrichment | **through 31 July 2026** (`gaz_asof_date`) |

**The dashboard intentionally treats Gazette-through-31-July as enrichment on top of the 1 July
snapshot, not as a contradiction of it.** Companies House status lags Gazette publication, so July
notices are the most valuable rows in the file, not contamination.

Affected populations, preserved as stored columns so they remain identifiable:

| Flag | Population |
|---|---|
| `gaz_new_in_july_flag` — first ever notice in July | **740** |
| `gaz_july_notice_flag` — any notice in July | **868** |

Of the 740, **656 are still "Active"** in Companies House and **586 have never been flagged
distressed** by CH at all.

**Condition on this decision:** if `gaz_*` fields are ever used as features in predictive modelling,
those 740 are circular and must be excluded (`gaz_new_in_july_flag = 1`) or the features re-derived
censored at 1 July from `nb10_gazette_notices_thru_2026-07.csv`, which still exists. That is a
modelling-time decision; the flags make it a one-line change.

### 4.2 Gazette filters inside All Companies

One dropdown with named states. **Never a bare "Gazette" toggle.**

| Option | Column | Population |
|---|---|---|
| No notice | `gaz_matched=0` | **1,511,569** |
| Any notice | `gaz_matched=1` | 19,525 |
| Severity: formal insolvency | `gaz_severity_tier='formal_insolvency'` | 17,136 |
| Notice in last 365 days | `gaz_recent_notice_365d_flag=1` | 9,722 |
| Active insolvency case | `gaz_active_case_flag=1` | 9,505 |
| Court involved | `gaz_court_involved_flag=1` | 3,410 |
| Winding-up petition | `gaz_has_winding_up_petition=1` | 2,711 |
| Notice in last 90 days | `gaz_recent_notice_90d_flag=1` | 2,216 |
| Severity: terminal | `gaz_severity_tier='terminal'` | 1,873 |
| Severity: early warning | `gaz_severity_tier='early_warning'` | 489 |

**Distinction from the dedicated view:** the Gazette Signal view *is* `gaz_matched=1` and ranks by
distress stage. The filter inside All Companies exists for the states the view cannot express —
above all **"No notice" (1,511,569)**, which is what makes preset G possible.

---

## 5. A / B / C

### A. FINAL — implement

**Views:** All Companies · Gazette Signal · Former LBG Client

**Core:** Segment · Status · Region · Industry (SIC) · Sector · Company age
**Borrowing:** Ever borrowed · Outstanding mortgages · Repayment state · New charge in 12m
**Lender:** LBG relationship · Main lender · Number of lenders · Competitor lender present ·
Competitor charge created (6m) · Competitor entered an LBG relationship (12m)
**Filing:** Accounts overdue · Overdue 6+ months · Confirmation statement late · No filing 24+ months
**Momentum:** Size tier moved · Relocated in 12m · Industry changed 12m
**Signals:** Lending readiness · Growth · Credit risk · Gazette (10 named states)

**Presets:** A · H · B · D · E2 · G · F2 · C · I

**Cross-cutting:** live counts on every option · header count · three-state NULL handling ·
explanatory zero-result state.

### B. OPTIONAL — useful, not essential

| Item | Population | Why optional |
|---|---|---|
| Lifecycle as a separate filter | 1,531,094 | Rollup of Status; offering both risks confusion |
| Changed name in 12m | 18,158 | Real but weak signal alone |
| Ever distressed before | 166,868 | Large, but overlaps Status and Gazette |
| Debt ratio trend 12m | 8,537 | 13.9% NULL, narrow |
| First ever award in 12m | 2,175 | Subsumed by F2 |
| Preset: Large/Medium never LBG | 26,123 | Overlaps B on a different axis |
| Preset: Multi-banked (refinance) | 7,586 | Reachable via Number of lenders ≥ 2 |
| Stricter B variant (no lender at all) | 2,500 | Sharper list if 8,992 proves too broad |

### C. EXCLUDE — do not build

| Item | Reason |
|---|---|
| **`size_tier`** | Redundant with `segment` — identical counts, adds only a 34.5% NULL group |
| **Preset: Sole lender a rival** | 56,684, but **90.7%** of what two dropdowns already give (62,465). Replaced by the Number of lenders filter |
| **Preset: F as originally specified** | Retained **93.5%** of "Won in 12m" — a repackaging. Replaced by F2 |
| **Preset: Growing and borrowing v1** | 364 companies. Replaced by E2 at 3,609 |
| **Voluntary exit score filter** | 998 of top 1,000 values are exact ties; cannot support banding or ranking |
| **`competitor_entered_12m` as a general competitor filter** | 230 companies and 100% LBG-relative. Keep only as its own precisely-labelled option |
| **Bare "Gazette" toggle** | Ambiguous. Ten named states instead |
| **Preset: Top prospect in a competitor's book** | 10,024 — largely redundant with B |
| **Preset: Young and already borrowing** | 696 — too small |
| **Preset: Just cleared their debt** | 4,013 — overlaps A |

---

## 6. Panel layout

```
[ All Companies 1,531,094 ] [ Gazette Signal 19,525 ] [ Former LBG 14,416 ]

Presets  [Proven borrower 31,003] [Unlevered growth 31,012] [Prospects we don't bank 8,992]
         [Exposure deteriorating 5,916] [Growing & borrowing 3,609] [Silent distress 2,520]
         [Contract winner, no borrowing 2,303] [Rival moved in 467] [Risk on our security 401]

┌─ Filter companies ─────────────── Showing 31,003 of 1,531,094 ──── Clear all ─┐
│ Core       Segment ▼  Status ▼  Region ▼  Industry ▼  Sector ▼  Age ▼         │
│ Borrowing  Ever borrowed ▼  Outstanding [≥__]  Repayment ▼  New charge 12m ▼  │
│ Lender     LBG relationship ▼  Main lender ▼ (86,468)  No. of lenders [≥__]   │
│            Competitor present ▼  Competitor charge 6m ▼  Entered LBG rel. ▼   │
│ Filing     Accounts overdue ▼  Overdue 6m+ ▼  Statement late ▼  No filing 24m+│
│ Momentum   Size move ▼  Relocated ▼  Industry changed ▼    (Not stated ✓)     │
│ Signals    Lending ▼  Growth ▼  Credit risk ▼  Gazette ▼                      │
└───────────────────────────────────────────────────────────────────────────────┘
```

Every option carries its live count. The header updates on every change. Presets populate the panel
rather than bypassing it, so a user can see what a preset did and adjust it.

> **Built 21 August 2026, see Section 10.** The shipped layout also groups these into Views, Tools
> and Result, with presets and filters in collapsible drawers; the requirement in the last sentence
> is met for eight of the nine presets, and 10.2 records why the ninth is a permanent exception.

**Zero-result state:** name the culprit — *"0 companies. 'Contract activity' reduced 56 → 0.
Remove it?"* — with one-click removal of the last-applied filter.

**Why live counts are mandatory.** Stacked filters collapse fast:

| Stack | Companies |
|---|---|
| Active | 1,409,284 |
| + segment Small | 374,875 |
| + outstanding mortgages > 0 | 53,086 |
| + former LBG | 2,807 |
| + competitor entered 12m | 56 |
| + won a contract in 12m | **0** |

Without counts, users build empty queries and conclude the tool is broken.

---

## 7. Decisions taken

All three were resolved in the build. The code is the record; this section says which way each went.

| # | Decision | Outcome | Where |
|---|---|---|---|
| 1 | F2 replaces F | **Taken.** `contract_no_borrowing`, "Contract winner with no borrowing", 2,303. The original F is not implemented in any form. | `serve.py` PRESETS |
| 2 | B tightened to trading segments | **Taken, at 8,992.** The stricter 2,500 variant ("no lender on the register at all") was not built. It stays available in Section 5B if 8,992 proves too broad. | `serve.py` PRESETS |
| 3 | Lifecycle instead of Status | **Taken: Lifecycle only.** `CompanyStatus` is not offered as a Core filter, so the two can never be presented side by side. The raw status still reaches the screen on the company page, where it is a fact about one company rather than a filter competing with a rollup. | `serve.py` FILTERS, Core group |

---

## 8. Implementation record

### 8.1 What was built, and where

| Piece | File | Note |
|---|---|---|
| Filter definitions | `dashboard/serve.py` | One declarative table driving three consumers: the WHERE builder, the facet-count endpoint, and `/api/filters`, which the UI renders itself from. Defining a filter once is what stops the panel and the query drifting apart. |
| Presets | `dashboard/serve.py` PRESETS | Each carries its spec population as `pop`. `/api/presets` recomputes live and returns both, so any drift between this document and the data shows up on screen instead of silently. |
| Panel, views, company page | `dashboard/index.html` | Reads `/api/*`. `data.js` is no longer loaded by the browser. |

The architecture changed underneath the spec: the browser is no longer where the company universe
lives. DuckDB reads the parquet in place and answers over all 1,531,094 companies, and the API
returns only the rows asked for. Nothing is precomputed into a store, no database file is created,
and the parquet is never written to. This is why every count in this document is now measurable at
runtime rather than baked at build time.

### 8.2 Live verification, 19 August 2026

Server started against `dashboard_bulk_gazette_2026-07.parquet`. Side tables loaded: 291,045
Gazette notices, 96 news rows, 1,496,693 identity rows.

**Presets: 9 of 9 match this document exactly.**

| Preset | Live | Spec |
|---|---|---|
| Proven borrower, no incumbent | 31,002 | 31,002 (was 31,003, see 9.4) |
| Established, unlevered, high growth | 31,012 | 31,012 |
| Best prospects we don't bank | 8,992 | 8,992 |
| Secured exposure deteriorating | 5,916 | 5,916 |
| Growing and borrowing | 3,609 | 3,609 |
| Silent distress, no Gazette yet | 2,520 | 2,520 |
| Contract winner with no borrowing | 2,303 | 2,303 |
| Lapsed client, rival moved in | 467 | 467 |
| High credit risk on our security | 401 | 401 |

**Views: all three match.** All Companies 1,531,094 · Gazette Signal 19,525 · Former LBG Client
14,416.

**Population figures confirmed live:** scored 1,409,284 and unscored 121,810 (the 8.0% NULL in
Section 2.6) · Gazette states all ten, from "No notice" 1,511,569 down to "early warning" 489 ·
LBG relationship current 11,733 / former 14,416 / never 1,504,945 · Repayment state 41,007 /
41,487 / 60,785 · Size tier moved up 19,003 / down 22,071 / none 856,217 / **Not stated 633,803** ·
Relocated yes 154,597 / no 1,162,931 / **Not stated 213,566**.

**Lifecycle distribution, measured live:** Trading 1,409,284 · Fading 97,721 · Insolvent 23,915 ·
Distressed 174.

**Filters: 27 implemented across the 6 groups**, which is Section 5A in full, less `Status` by
decision 3.

| Group | Count | Filters |
|---|---|---|
| Core | 6 | segment, lifecycle, sector, age, region, industry |
| Borrowing | 4 | ever_borrowed, outstanding, repayment, new_charge_12m |
| Lender | 6 | lbg, main_lender, lenders, competitor, competitor_6m, competitor_lbg |
| Filing | 4 | overdue, overdue_6m, confstmt_late, no_filing_24m |
| Momentum | 3 | size_move, relocated, sic_changed |
| Signals | 4 | lending, growth, risk, gazette |

**Cross-cutting requirements from Section 5A: all four present.** Live counts on every option
(served by `/api/filters`) · header count, rendered as "Showing N of M" · three-state NULL handling
· explanatory zero-result state naming the last filter applied, with one-click removal.

**The stacked-filter collapse in Section 6 reproduces exactly**, which verifies the composition
path rather than any single clause: Trading 1,409,284 → + segment Small 374,875 → + outstanding > 0
53,086 → + former LBG 2,807 → + competitor entered 12m **56**. The sixth step in that table, "won a
contract in 12m", cannot be reproduced because contract activity exists only inside preset F2 and
is not offered as a standalone filter.

**Latency, measured on the running server.** Full panel repaint `/api/filters` 0.58s cold, 0.81s
with two filters active. `/api/browse` 0.20s. `/api/presets`, which recomputes all nine populations
over 1.5M rows, 0.17s. A panel repaint issues roughly 57 aggregate queries, one per option, and
DuckDB absorbs that without a cache. No optimisation is needed.

**The labelling defects this spec was written after are gone.** Spot-checked live: a Gazette-view
company returns status `Liquidation`, lifecycle `Insolvent`, four notices, stage 5 "Final meeting",
and `scores: null` because it sits outside the scored population. A `silent_distress` company
returns lifecycle `Trading` with **no Gazette block at all**, which is the point of the preset. No
company is labelled Fading while insolvent, and none carries a Gazette chip without a notice.

### 8.3 Deviations from the specification as written

Small, deliberate, and recorded so the next reader does not treat them as bugs.

| Item | Spec said | Built as | Why |
|---|---|---|---|
| Region, Industry | "needs type-ahead, not a dropdown" | `kind: search`, backed by `/api/options` | 175 and 727 values respectively. Same intent, named. |
| NULL sentinel | "Not stated" as a third state | `__notstated__` on `choice` filters, `notstated` on `tri` | Two filter kinds needed it, so the value differs by kind. The label is "Not stated" in both. |
| Gazette option labels | Prose, e.g. "Notice in last 365 days", "Severity: terminal" | ~~Terse, e.g. "recent 365", "terminal"~~ **Resolved 21 August 2026, see 10.3.** | The prose from Section 4.2 is now served as the option label. Values, predicates and counts are unchanged. |
| Zero-result copy | Names the culprit with before and after, "reduced 56 → 0" | Names the last filter applied and offers to remove it | The undo works; the before-and-after number is not shown. |
| **Presets and the panel** | "Presets populate the panel rather than bypassing it, so a user can see what a preset did and adjust it" | ~~A preset is a toggle chip carrying an opaque server-side clause.~~ **Resolved 21 August 2026: presets now load into the controls. See Section 10.** | This was the one substantive deviation. It is closed for eight of the nine presets; the ninth cannot be expressed in the approved filter set and is documented in 10.2. |

### 8.4 Open items

1. ~~**Presets do not populate the panel**, which Section 6 asked for. Ranked first because it is the
   only deviation that changes what the tool can do rather than how it reads. See 8.3.~~
   **CLOSED 21 August 2026, see Section 10.** Eight of the nine presets now load into the filter
   controls and can be adjusted. The ninth is documented there as a permanent exception.
2. ~~**Gazette option labels** should carry the prose from Section 4.2. The counts are right and the
   states are right; the words are the raw keys.~~
   **CLOSED 21 August 2026, see Section 10.3.** Raw keys became unacceptable once a preset started
   stating its conditions in these words, so a display-only label map was added.
3. **The stricter B variant** (2,500, no lender on the register at all) is specified but not built.
   Decide from use whether 8,992 is too broad.
4. **Section 5B optional filters** are all unbuilt, as intended.
5. **The `gaz_new_in_july_flag = 1` exclusion in Section 4.1 is a modelling-time condition and has
   not been applied anywhere.** The flag exists in the parquet, so it stays a one-line change. It
   must be honoured before any `gaz_*` field is used as a model feature; the 740 companies are
   circular. Nothing in the dashboard does this today, which is correct, because the dashboard
   describes rather than predicts.
6. **`data.js` is still on disk at 27 MB** purely so the server can lift its 20-key meta block at
   startup. Moving that block to a small config file would remove the file entirely.
7. **`/api/watchlist` still treats any unrecognised `view` as "gazette"**, the last silent fallback
   left in the API. It is not reached by the UI, which is why it was left alone in the 19 August fix
   pass; fix it if that endpoint is ever wired up.

---

## 9. Adversarial verification and fix pass, 19 August 2026

A full verification pass was run against the live server: independent DuckDB ground truth written
from column semantics rather than copied from `serve.py`, with every count check paired with a
row-level re-test of each returned company. Roughly 400 assertions.

### 9.1 The filtering logic was correct

63 facet counts, 34 filter cases, 9 presets decomposed into 36 individual conditions, 22 hand-built
combinations including 8 deliberate contradictions, and 120 seeded random combinations produced
**zero count mismatches and zero rows that failed the predicate they were selected by**. NULL
handling held everywhere it is hardest: "No" is observed-false throughout, no score filter leaks a
non-Active company in either direction, and momentum NULLs are consistently a third state rather
than a negative. `is_active` is exactly `CompanyStatus = 'Active'`, 0 rows either way. Every
injection attempt returned 0 rows.

### 9.2 Five defects found and fixed

| ID | Defect | Fix |
|---|---|---|
| B1 | **Ordering was non-deterministic.** The Gazette Signal and Former LBG views order by non-unique keys with no tie-break, so DuckDB's parallel scan was free to arrange ties differently each run. Five identical calls to the LBG view returned five different sets of companies; walking six pages of 100 showed 526 distinct companies in 600 slots, so **74 were never displayed**. It reached the UI: growing the list from 25 to 50 moved 15 of the 25 visible rows. | `TIE_BREAK = ", CompanyNumber ASC"` appended to every ordered query: both view orders, the default name order, the custom `sort` branch, `order_by()`, `/api/watchlist` and `/api/search`. `CompanyNumber` is unique across all 1,531,094 rows and never null, so the sort is now a total order. |
| B2 | A negative `limit` reached DuckDB as `LIMIT -5` and returned **HTTP 500**. Only offset was floored. | `paging()` clamps limit at both ends. Zero stays legal as a count-only request. |
| B3 | **Unrecognised values failed open.** `gazette=not_a_state`, `repayment=bogus`, `preset=not_a_preset`, `view=not_a_view`, `relocated=maybe` each silently dropped the filter and returned the **full 1,531,094**, while `segment=NoSuchSegment` correctly returned 0. Same user error, opposite outcomes, and the failure widened the result set. | New `FilterError` with a 400 handler. Unknown `choice`, `tri`, `bool`, `preset` and `view` values are rejected with the list of valid options. Absent or empty still means "filter off". |
| B4 | `age_min=nan`/`inf` parsed as floats and silently returned 0; `age_min=abc` silently returned everything. Two kinds of bad input, two silent and opposite outcomes. | Both rejected with 400. |
| B5 | 27 matched companies carry the real severity tier `'none'`, but `_txt()` treats the literal string "none" as a null marker (correct for the CSV side files, wrong here), so those rows rendered as `· 2 notices` with a dangling separator. | New `_cat()` used for `gaz_severity_tier` only, plus `TIER_LABEL` in the UI rendering it "No severity tier". **Stored values and every filter predicate are unchanged.** |

### 9.3 Re-verification after the fixes

All of the above re-run and passing: 10 identical calls per view and offset return identical rows;
page walks of 300 to 600 slots show zero duplicates and zero skipped companies; the first 25 rows
stay fixed as the list grows 25 → 50 → 100; four pages of 25 equal one call for 100; custom sorts,
presets, filtered subsets and the legacy endpoints are all stable. Every rejection case returns 400
with a useful message and every valid case still returns 200 with an unchanged count. The full
original suite passes unchanged: facets, row-level, presets, combinations, the 120-combination
fuzz. The page still serves and the inline JS passes `node --check`.

### 9.4 D1 resolved: preset A moved off `debt_ratio`, one company affected

Preset A's `debt_ratio = 0` was compared against `Mortgages.NumMortOutstanding = 0`:

| Definition | Population |
|---|---|
| current, `debt_ratio = 0` | 31,003 |
| alternative, `outstanding = 0` | 31,002 |

**The alternative is a strict subset; nothing new enters** (0 companies have `outstanding = 0` with
`debt_ratio > 0`). The single differing company is **ANTALIS LIMITED, 01088345**: 416 charges, 2
still outstanding, 414 satisfied. The true ratio is 0.0048, and `debt_ratio` is rounded to two
decimals upstream (99 distinct values in the file), so it stores as 0.00. It is the only company in
the whole file whose ratio falls in the 0 to 0.005 band. It is Large, has one lender,
`primary_lender_group = other_bank`, and is not an LBG client, so it sits in a preset titled "no
incumbent to displace" while holding two charges with an incumbent.

The same rounding affects "Repayment state: fully repaid" identically, one company of 41,007. The
opposite direction is clean: 0 companies round up into `debt_ratio = 1`. Presets H and F2 test
`Mortgages.NumMortCharges = 0` and are untouched by rounding.

**Decision taken: preset A now tests `Mortgages.NumMortOutstanding = 0`.** 31,003 → 31,002, one
company removed, none added. Re-verified: presets decomposed per condition, combinations, facets,
row-level and the 120-combination fuzz all pass, and the ordering fixes are unaffected.

### 9.5 What the cross-verification uncovered: two "outstanding" measures

Cross-verifying the change before making it showed that the file carries **two different
"outstanding" measures, and they disagree**. Section 9.6 establishes which one to trust; this
section is the raw finding.

| | |
|---|---|
| `Mortgages.NumMortOutstanding` | the Companies House bulk count |
| `n_charges_outstanding` | the charge-level lender pipeline |

They differ on 2,859 companies, and on **1,300 one is zero while the other is not** (1,283 where
the bulk says nothing is outstanding but the charge pipeline says otherwise, 17 the reverse).

**Every lender field is built on `n_charges_outstanding`, not on the bulk column.** Verified:
`primary_lender_group IS NOT NULL AND n_charges_outstanding = 0` is **0** companies, while
`primary_lender_group IS NOT NULL AND Mortgages.NumMortOutstanding = 0` is **996**.

The consequence for preset A, whose whole promise is "no incumbent to displace":

| Definition of "no incumbent" | Population | Still carrying a named lender | Current LBG clients |
|---|---|---|---|
| `debt_ratio = 0` (before) | 31,003 | **662** | **118** |
| `Mortgages.NumMortOutstanding = 0` (now) | 31,002 | **661** | **118** |
| `n_charges_outstanding = 0` | 30,177 | **0** | **0** |
| `Mortgages.NumMortOutstanding = 0 AND primary_lender_group IS NULL` | 30,341 | **0** | **0** |

Concrete examples in the current preset: TWICKENHAM PLATING LIMITED (00463525), bulk says 16 charges
all satisfied, the charge pipeline says 4 outstanding with **LBG** as primary lender and
`is_lbg_client = true`. MEGGITT LIMITED (00432989), bulk says 2 of 2 satisfied, pipeline says 2
outstanding with HSBC. By lender: hsbc 127, **lbg 110**, other_bank 27, challenger_bank 12.

> **The paragraph that stood here was wrong and has been replaced by 9.6.** It read the 661 as
> "661 companies wrongly in a prospecting list, a business error", and recommended moving preset A
> onto `n_charges_outstanding = 0`. Section 9.6 investigated that and found the opposite: those 661
> are overwhelmingly decades-old register entries rather than live incumbents, and the recommended
> change would have deleted genuine prospects. The table above is still accurate as counts; the
> interpretation of it was not.

### 9.6 Which of the two is authoritative, investigated 19 August 2026

**Provenance.**

| | `Mortgages.NumMortOutstanding` | `n_charges_outstanding` |
|---|---|---|
| Source | Companies House **monthly bulk download**, Block A | Companies House **Charges API harvest**, Block D, `14b_lender_charges.ipynb` |
| As-of | `base_month` 2026-07-01, `source_date` 2026-07-01 | **not recorded anywhere in the parquet** |
| Granularity | a summary count, **no lender attribution at all** | charge-level, with lender identity, satisfaction dates, LBG flags |
| Gating | none stated | panel variant `lender_panel_calib`, gating each charge on `visible_on(4d)` and `satisfied_on + 1d` against the real extract date |

The handover describes Block D as "descriptive only: none of these fed any score". Unlike the
Gazette block (`gaz_asof_date`) and the contracts block (`contracts_asof_month`, `contracts_stale`),
**the lender block carries no as-of date and no staleness flag**, so its currency cannot be checked
from the file. That is a gap worth closing at source.

**The disagreement is a function of company age, not of freshness.** Among companies the charge
pipeline says have an outstanding charge:

| Company age | Pipeline says outstanding | Bulk disagrees | Rate |
|---|---|---|---|
| under 10y | 20,592 | 21 | **0.10%** |
| 10-20y | 30,298 | 49 | 0.16% |
| 20-30y | 26,988 | 70 | 0.26% |
| 30-50y | 18,112 | 442 | 2.44% |
| **50y+** | 7,549 | 701 | **9.29%** |

A ninety-fold gradient. Supporting evidence: the disputed LBG relationships carry an **average charge
age of 34.4 years** against 12.9 years where the two sources agree, and **88 of 173 have no
satisfaction record at all**. Of the 118 current LBG clients inside preset A, 86 hold a charge over
30 years old and only **4 hold one under 10 years**. The reverse direction (17 companies) shows no
age gradient at all and is noise.

This is the signature of charges left open on the register because a satisfaction was never filed,
not of live secured borrowing. The `satisfied_on + 1d` gate holds a charge open whenever that date
is missing, which is exactly the condition expected on a 1980s charge.

Not a register artefact either: England and Wales disagrees more (0.088%) than Scotland (0.020%) or
Northern Ireland (0.015%).

**The bulk is not flawless.** Its own three counts fail to reconcile on **463 companies** (182 of
them inside the disputed set), and on **41 companies** the pipeline sees more outstanding charges
than the bulk records as ever having existed.

**Conclusion.**

- For **"is there currently outstanding borrowing"**, the bulk column is the better field. The
  pipeline over-counts stale legacy charges structurally, not randomly.
- For **"who is the incumbent lender"**, only the pipeline can answer, because the bulk carries no
  lender information. But its incumbency claims inherit the same staleness, so a
  `primary_lender_group` on a company the bulk says has nothing outstanding is usually a decades-old
  entry rather than a bank relationship.
- **Preset A stays on `Mortgages.NumMortOutstanding = 0` and needs no further change.** Adding
  `n_charges_outstanding = 0` would take it from 31,002 to 30,163, removing 839 companies that are
  mostly register artefacts. That would delete real prospects to fix a phantom.

**Limits of this evidence.** Charge age is measurable only for the LBG subset, since
`months_since_last_lbg_charge_created` is the only charge-date column in the file; for the other 543
lendered companies in preset A the live-versus-stale split is inferred from the same gradient rather
than measured. `charges_flat.parquet`, named in the handover as existing upstream, would settle it
at charge level by checking `satisfied_on` nulls. It is not on disk in this repo.

**Optional, not required by the evidence.** Adding `NOT is_lbg_client` to preset A gives 30,884 and
guarantees a current LBG client never appears in it, at a cost of 118 companies of which 4 look
live. Preset A does not promise "not banking with us" (that is preset B), so this is presentational
tidiness rather than a correctness fix.

---

## 10. Presets made visible and adjustable, 21 August 2026

Closes open items 1 and 2 from Section 8.4, and with them the last substantive deviation in 8.3.
**No filter definition, preset definition, score, source integration or company data changed.**

### 10.1 What a preset does now

A preset carries a second expression of itself written in the panel's own vocabulary. Selecting one
loads those conditions into the Advanced Filters controls, so a banker can see exactly what was
applied and change any part of it:

```
Silent distress, no Gazette yet   2,520 companies                      [Remove]
Both filing signals failed, nothing has reached the Gazette.
[LIFECYCLE Trading] [GAZETTE No notice] [OVERDUE 6+ MONTHS Yes] [CONFIRMATION STATEMENT LATE Yes]
Open Advanced filters to loosen or change any of these.
```

Those four controls are genuinely selected in the panel; the chips are read back off the live filter
state, not off a stored description, so the list stays true after an edit.

| Behaviour | How it works |
|---|---|
| Preset stays identifiable | Chip pressed, drawer badge reads "1 selected" or "1 adjusted", and the bar sits outside the drawers so closing them hides a control, never a fact |
| Selecting replaces, not stacks | The count on the chip is the count you get. The panel as it stood beforehand is snapshotted |
| Clearing restores | **Remove** puts back the pre-preset panel rather than emptying it |
| Adjusting is obvious | The bar turns amber with an "adjusted" tag, the count is replaced by a line naming what the preset alone would return, and the button becomes **Reset** |
| Reset | Restores the preset exactly as approved, without removing it |

`where` remains the definition of a preset. The count is always computed from `where`, never from
the mapping, so the two cannot drift silently in the direction that matters.

### 10.2 The one preset that cannot be taken apart

**`contract_no_borrowing` has no mapping, permanently.** Its `contracts_won_12m > 0` condition has no
filter control in the approved set, and the preset expressed without it returns **805,602 companies
instead of 2,303**. Inventing a contracts filter would change the filter system this document
verified, so the preset stays exactly as it was: applied server-side from `where`, with its four
conditions listed as fixed, dashed chips and the reason stated on screen.

> This one also requires: **won a public contract in the last 12 months**, which has no filter
> control, so this preset cannot be taken apart here.

Adding a contracts filter is the only thing that would close this, and that is a Section 5 decision,
not a UI one.

### 10.3 Choice labels, display only

Options were rendering as their raw keys: "none", "top10", "recent_365". That was tolerable while
they were dropdown entries and stopped being tolerable the moment a preset began stating its
conditions in those words. A `CHOICE_LABELS` map now supplies the Section 4.2 prose for Gazette and
readable names for the other `choice` filters.

**Values, predicates and counts are untouched.** Verified after the change: `value=none` still
returns 1,511,569, `value=any` 19,525, `value=formal_insolvency` 17,136.

### 10.4 Verification, 21 August 2026

**The mapping was verified before any UI was written, by SET DIFFERENCE rather than by count** — two
predicates can agree on a total and still select different companies. For each preset, the companies
matched by `where` and the companies matched by `filters` were compared in both directions:

| Preset | `where` | expansion | only in `where` | only in expansion |
|---|---|---|---|---|
| proven_borrower | 31,002 | 31,002 | 0 | 0 |
| unlevered_growth | 31,012 | 31,012 | 0 | 0 |
| prospects_not_banked | 8,992 | 8,992 | 0 | 0 |
| exposure_deteriorating | 5,916 | 5,916 | 0 | 0 |
| growing_borrowing | 3,609 | 3,609 | 0 | 0 |
| silent_distress | 2,520 | 2,520 | 0 | 0 |
| **contract_no_borrowing** | **2,303** | **805,602** | **0** | **803,299** |
| rival_moved_in | 467 | 467 | 0 | 0 |
| risk_on_our_security | 401 | 401 | 0 | 0 |

Two equivalences in that table are worth recording because they are not obvious:

- `lifecycle = Trading` is exactly `is_active`. Verified in 9.1: `is_active` and
  `CompanyStatus = 'Active'` disagree on 0 rows in both directions.
- `lbg = current` is exactly `n_lbg_charges_outstanding > 0`. Verified in 9.1: `is_lbg_client` with
  no outstanding LBG charge is 0 rows, and an outstanding LBG charge without `is_lbg_client` is 0
  rows.

**Driven in a real browser**, each step confirmed against the API: select (2,520, four controls
populated) → loosen one condition (4,917, bar adjusted, button becomes Reset) → Reset (back to 2,520
pristine) → Remove (the pre-preset filter returns at 239,957) → the non-adjustable preset (2,303,
four fixed chips) → an impossible bound on top of a preset (0, zero-state names "Company age", undo
recovers to 2,520 with the drawers still open).

**Regression suite, all passing:** facet counts, browse totals with row-level re-testing, presets
decomposed per condition, combinations, 120-combination fuzz (0 count mismatches, 0 row violations),
ordering determinism (23 checks), defensive input handling, severity labelling. Source integrations
confirmed intact: six live, none pending.

### 10.5 Logo 404s

`brand()` probed `assets/lloyds-logo.svg` and `assets/lloyds-logo.png` before falling through to the
mark that exists, so **every page load logged two 404s**. Neither file was ever added; the naming
convention lived only in `assets/README.txt`. The probe list now names what is on disk, and the
README records that the list is fetched with real requests, so any name in it that is not present
costs a 404 on every load.

The favicon was inlined as a data URI at the same time, which removes the browser's automatic
`/favicon.ico` request. **A normal page load now produces zero console errors.**
