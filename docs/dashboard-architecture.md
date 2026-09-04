# The dashboard, end to end: what it is, how it fetches data, and how to extend it

**Built 25 August 2026** from a read-only crawl of `origin/vishal/dashboard` (commits `d4071ff`,
`df4fd84`, `8ebeef6`, all 24 August), cross-read against Vishal's own two documents
(`dashboard/dashboard_handbook.md`, `dashboard/dashboard_design.md`), the decision log
(`dashboard/FILTER_SPEC.md`), and the code itself (`dashboard/serve.py`, `dashboard/index.html`).

This document exists so that somebody, or some agent, who has never seen the repository can be
pointed at it and then give Vishal precise, correct instructions: "wire this CSV in as a source",
"add this filter", "add this page". It is the companion to `drafts/project-chronology-2026-08-08.md`,
which is the narrative of everything before it.

Everything below is what the branch actually contains. Where Vishal's prose and the code disagree,
the code wins and the disagreement is flagged.

---

## 0. The one-paragraph version

The dashboard is **a single static HTML page plus a small local Flask server that queries a Parquet
file through in-process DuckDB**. There is no database file, no build step, no framework, no bundler,
and nothing is precomputed. `python dashboard/serve.py` opens an in-memory DuckDB connection, loads
nine small CSV side tables into it, computes six score quantiles once, and then serves JSON out of
about a dozen `/api/*` endpoints. `index.html` is 4,462 lines of vanilla JS with zero dependencies; it
fetches JSON and builds DOM. The company universe lives in one Parquet on disk, 1,531,094 rows by 124
columns, and is read in place on every request with `read_parquet(?)`. **The browser never holds the
universe.**

---

## 1. Architecture, and the two designs it is not

This matters because half of what is on disk is residue from the earlier designs, and reading the
repository without knowing that will mislead you.

**Design 1, the signals table (June/July, in `reports/integration-design.md`).** Every pipeline gets a
~30-line adapter emitting one row per company per fact per date
(`company_number, signal_type, signal_date, value, detail, source, confidence, retrieved_at`), all
precomputed into a store the dashboard reads. Never built as such, but three of its rules survived
into everything downstream and are still the house style:

1. Always join on company number, never on company name.
2. Every signal must have a real date, no nulls.
3. **A company with no signals is a real answer, not a missing one.** This is the single most durable
   idea in the whole dashboard, and it is why "not searched" and "searched, found nothing" are
   different states on screen everywhere.

**Design 2, the sharded browser store (early August, the `data.js` era).** The store was shipped to
the browser as JavaScript because `file://` blocks `fetch()`. One file hit 27MB holding only part of
what was needed and the full set projected to 85-100MB, so it was sharded: a ~5MB `core.js` loaded at
startup (the 105,078 signalled companies: number, name, status, sector, segment, and a bitmask of
which sources each has), then `features/<src>/NN.js` and `events/<src>/NN.js` shards keyed on **the
last two characters of the company number**, pulled in on demand by injecting a `<script>` tag. Search
only ever needed `core.js`, because search is over identity, not evidence.

It was a sound design and it was still wrong, for one reason: **everything in it is a build artefact.**
The 105,078 was the set of companies with a signal *at build time*. The browser held a second copy of
the data that could drift from the Parquet, the 1.43M companies without a signal could not be filtered
at all because they were not in the store, and every new filter meant regenerating 100 shards.

**Design 3, what exists now: query in place.** DuckDB reads the Parquet in place and answers over all
1,531,094 companies; the API returns only the rows asked for. Nothing is precomputed, no database file
is created, and the Parquet is never written to. The consequence that Vishal keeps repeating is the
right one to keep in mind when instructing him: *every count on screen is measurable at runtime rather
than baked at build time, so the dashboard cannot disagree with the data, because there is no second
copy to disagree with.*

**Residue you will trip over.** `dashboard/build_data.py` (758 lines) is the Design-2 builder. It is
still in the tree and still works, but the server does not use it for data any more. `data.js` is
gitignored and not on the branch, but if a teammate has one locally it can be 27MB on disk purely so
the server can lift a 20-key metadata block at startup, which is why `dashboard/store_meta.json` (98
lines) now exists as the small replacement. `load_build_meta()` prefers `store_meta.json` and falls
back to `data.js`. Do not send Vishal instructions that touch `build_data.py` unless you actually mean
the legacy static build.

**Why DuckDB and not PyArrow.** Vishal benchmarked it on this dataset. Filtering (28ms vs 25ms) and
name search (65ms vs 52ms) are near ties. The decision came from the other four rows: aggregation 9x
(151ms vs 17ms), sorting 12x (370ms vs 30ms), startup 83x (~2s vs 24ms), and memory **444MB vs 0.2MB**,
because PyArrow materialises the table and DuckDB streams from the Parquet. Aggregation settled it: a
single facet repaint fires ~57 aggregate queries because every filter option carries a live count.
That benchmark is **not in any repository file**; it lives only in Vishal's working record and in
`dashboard_design.md` section 2.

---

## 2. Running it

```
python dashboard/serve.py                 # opens http://127.0.0.1:8000 by itself
python dashboard/serve.py --no-browser
python dashboard/serve.py --data /path/to/data --parquet /path/to/other.parquet --port 8000
```

Needs `duckdb`, `flask`, `pandas`. Takes about fifteen seconds to start because it loads the side
tables and computes the quantiles first, and it prints what it found while doing so.

**Data path resolution, in order:** `--data` on the command line, then the `LLOYDS_DATA` environment
variable, then `DEFAULT_DATA = Path(r"C:\Users\visha\Lloyds_Github\data")`. That last one is a
fallback, not a requirement, and it is the fix for the hardcoded-Windows-paths blocker recorded in the
chronology's Stream H. If the Parquet is missing it prints exactly what it looked for and what the
data tree is taken to be, rather than a stack trace.

**Expected tree under `<data>`:**

```
<data>/processed/dashboard_bulk_gazette_2026-07.parquet   the spine, 1,531,094 x 124
<data>/processed/nb10_gazette_notices_thru_2026-07.csv    291,045 notices
<data>/processed/nb14_news_signals_2026-06-30.csv         96 searched companies
<data>/processed/filtered_bb_sme_sectors_all_status_2026-08-01.csv   identity fallback
<data>/processed/sam_sc/data/*.csv                        Samuel's six pack files
<data>/raw/dashboard_bulk_2026-07.parquet                 the un-enriched 69-col version
<data>/../market_analysis/*.csv                           Sneha's three saved outputs
```

Note `MARKET = DATA.parent / "market_analysis"`, one level **above** the data tree. That is a real
trap if you move the tree.

---

## 3. The data layer, precisely

### 3.1 The spine

`dashboard_bulk_gazette_2026-07.parquet`, **1,531,094 rows x 124 columns**. It is
`dashboard_bulk_2026-07.parquet` (Viktor's 69-column handover file, built 10 August by
`notebooks/20_dashboard_handover.ipynb`, scores from run `refactor_growthfix`) with **55 `gaz_`
columns** joined on by `notebooks/13_merge_bulk_gazette.ipynb`. It is a verified strict superset: every
one of the raw file's 69 columns is present. `--parquet` can point at the raw file instead; the
universe is identical, but no Gazette question can be answered.

`reports/dashboard_handover_columns.md` (on `sneha-viktor/shap`) and
`dashboard/dashboard_handover_columns.md` (same file, on the dashboard branch) are the column
dictionary. Three things from it to keep in mind:

- **7.96% of rows carry no scores and that is correct.** Scores exist only where `CompanyStatus` is
  exactly `Active`, 1,409,284 of 1,531,094.
- **Contract columns are as at 2026-05-01, not July**, deliberately, because Find a Tender's feed ends
  5 June 2026 and June/July coverage is partial. They are display-only and did not feed the scores.
- **Counts and flags coalesce to 0/false; `months_since_*` stays NULL.** No row means "never", and a
  zero would read as "this month".
- `sector IS NOT NULL` recovers the widened universe from the file, so no second extract is needed.

**The universe question, settled by fiat.** The dashboard uses 1,531,094, which is none of the three
lists the chronology argued about (Sam's spine 869,043, the SHAP feature matrix 1,372,321, the panel
2,038,130). What matters is not which number won but that **the universe is never narrowed**: the
"All companies" view applies no predicate at all, so every count on screen is a count out of
1,531,094 and never out of some earlier subset nobody remembers choosing.

### 3.2 The side tables

Loaded once at startup by `load_aux(con)` (`serve.py:1552`) as **in-memory DuckDB tables**, not files
on disk, each read with `read_csv(..., all_varchar=true, ignore_errors=true)` and each given a `cn`
column produced by the shared SQL cleaner:

| Table | File | Rows |
|---|---|---|
| `notices` | `processed/nb10_gazette_notices_thru_2026-07.csv` | 291,045 |
| `news` | `processed/nb14_news_signals_2026-06-30.csv` | 96 |
| `news398` | `sam_sc/data/news_coverage_summary.csv` | 398 |
| `tm_f` / `tm_e` | `sam_sc/data/ipo_trademarks_company_features.csv` / `_events.csv` | 15,713 / 93,795 |
| `grants` | `sam_sc/data/ukri_grants_company_features.csv` | 10,254 |
| `prop_f` / `prop_e` | `sam_sc/data/land_registry_company_features.csv` / `_events.csv` | 60,629 / 318,068 |
| `ident` | `processed/filtered_bb_sme_sectors_all_status_2026-08-01.csv` | identity fallback, deduped by `QUALIFY row_number() OVER (PARTITION BY cn) = 1` |

**The rule that decides what a source can do, and it is the single most important architectural fact
for anyone planning an addition:**

> **Anything on the spine can be filtered. Anything in a side table can only be shown on a profile.**

Borrowing, lender, filing, momentum, Gazette and the model scores are columns on the Parquet, so they
are filterable. Property, trade marks and grants are side tables keyed on company number, so they
appear on a company page and nowhere else. This is why the filter panel has no "has property" control,
and it is not an oversight. It is also why one preset can never be taken apart (section 7).

### 3.3 The company-number cleaner

One SQL template, `CLEAN_CN` (`serve.py:~395`), applied to every side table as it loads, plus a Python
twin `clean_number()` for values arriving off the URL. Upper, trim, strip spaces; `''`, `'NAN'`,
`'NONE'` all resolve to NULL rather than to a company called "NAN"; numeric strings zero-padded to at
least 8; non-numeric strings of 8 or fewer characters zero-padded to 8; anything else NULL. The
comment records that it was verified row-for-row against the Python cleaner in `build_data.py` on
**3,027,787 rows, 0 mismatches**. Two cleaners exist and they were checked against each other rather
than assumed to agree.

---

## 4. The request path, step by step

```
browser (index.html, vanilla JS)
   |  fetch("/api/browse?view=all&segment=Small&lbg=never&limit=25")
   v
Flask route  ->  build_filter_where(request.args)   walks the FILTERS table
   |            + view_where(view)                  three named populations
   |            + sql_of()                          substitutes __LIFECYCLE__ and the 6 quantiles
   v
DuckDB:  SELECT <LIST_SELECT>, <LIFECYCLE_SQL> AS lifecycle
         FROM read_parquet(?)  WHERE (<view>) AND (<filters>)
         ORDER BY ... NULLS LAST, CompanyNumber ASC
         LIMIT ? OFFSET ?
   |
   v
list_record(r) per row  ->  jsonify  ->  browser builds DOM
```

Every request opens its own cursor off one shared connection (`q()`, `serve.py:418`) so concurrent
requests do not share state. There is **no cache anywhere** except `_MARKET_CACHE` for the Analytics
page, and the record says plainly why none is needed: a full panel repaint is ~57 aggregate queries at
0.58s cold, and `/api/presets` recomputes all nine populations over 1.5M rows in 0.17s.

**Safety.** Every value reaching SQL goes through a DuckDB parameter, and every column name is checked
against an explicit allow-list. A filter key or sort key the server does not recognise is rejected,
not interpolated. Every injection attempt in the verification pass returned 0 rows.

### The endpoints

| Endpoint | What it does |
|---|---|
| `GET /api/health` | Parquet path and universe count |
| `GET /api/meta` | Universe size, live facet counts, source status, score-model definitions, news counts. The config half is lifted from `store_meta.json`, the counts are computed live |
| `GET /api/company/<n>` | One company in the exact shape the page renders (see `full_record()`) |
| `GET /api/company/<n>/raw` | Every Parquet column untransformed, for debugging |
| `GET /api/search?q=` | Company number if it looks like one, otherwise name `LIKE '%q%'`, ordered by `length(CompanyName), CompanyName` so exact-ish names float |
| `GET /api/watchlist?view=` | The two ranked landing views, over the whole universe |
| `GET /api/filters?<state>` | **The panel renders itself from this.** Groups, labels, kinds, and every option's live count |
| `GET /api/options?key=region\|industry&q=` | The two search-only facets (175 regions, 727 industries, too many to count eagerly) |
| `GET /api/presets` | Nine presets, populations recomputed live from `where` |
| `GET /api/browse?<state>` | The result list: view + filters + preset, one page, plus `total` and `universe` |
| `GET /api/market` | Sneha's competitive analysis, computed once and cached |
| `GET /api/filter`, `GET /api/aggregate` | Legacy generic endpoints on the older allow-lists (`TEXT_FILTERS`, `BOOL_FILTERS`, `NUMERIC_FILTERS`, `DERIVED_FILTERS`). Not used by the current UI |
| `GET /`, `GET /<path>` | Static files out of `dashboard/` |

---

## 5. The filter system, which is the part you will most often want changed

### 5.1 One declarative table, three consumers

`FILTERS` in `serve.py:69-152` is a single dict of 27 filters across six groups (Core, Borrowing,
Lender, Filing, Momentum, Signals). It drives **three** things: the WHERE builder (`clause_for`), the
facet-count endpoint, and `/api/filters`, which the UI renders itself from. **Defining a filter once
is what stops the panel and the query drifting apart.** The panel is not hand-written HTML: the browser
asks the server what filters exist and draws whatever it is told, so a filter cannot appear in the UI
without a predicate behind it, and a predicate cannot change without the panel following.

### 5.2 The six `kind`s

| `kind` | Shape | Emits |
|---|---|---|
| `in` | `value IN (...)` on a column | multi-select, `__notstated__` handled as `IS NULL` |
| `in_expr` | same on a SQL expression | e.g. `lifecycle`, `region` |
| `tri` | Yes / No / Not stated | `IS TRUE` / `IS FALSE` / `IS NULL` |
| `bool` | simple true filter, no NULLs exist in the column | `(expr)` / `NOT (expr)` |
| `range` | numeric `_min` / `_max` | `>=` / `<=` |
| `choice` | a named set of predicates | one OR'd clause per selected key |

Two placeholders are substituted at query time by `sql_of()`: `__LIFECYCLE__` expands to the
`LIFECYCLE_SQL` CASE block, and `__P99_LENDING__` / `__P90_LENDING__` / `__P99_GROWTH__` /
`__P90_GROWTH__` / `__P99_RISK__` / `__P90_RISK__` expand to floats computed once at startup with
`quantile_cont(...)` over the Active population. Score thresholds are population-wide constants, so
they are computed once rather than as a correlated subquery inside every filter.

### 5.3 The NULL rule, which is the most consequential design decision in the system

> **A missing value is never treated as a negative.** Every filter with NULLs offers three states,
> Yes / No / Not stated, where "No" means *observed false*, not *unknown*.

It exists because the NULL rates are enormous and each means something specific:

| Filter | NULL rate | What NULL actually means |
|---|---|---|
| Main lender | **94.4%** | No outstanding charge. Not "unbanked" |
| Size tier moved | 41.4% | No 12-month history, or no segment to move |
| Relocated / Industry changed | 13.9% | Incorporated less than 12 months ago |
| Model scores | 8.0% | Company is not Active, so it was never scored |

Collapsing any of those to "No" would produce a confidently wrong list. This rule is mirrored in the
frontend by `_tri()` in `serve.py` and by the tri-state controls in `index.html`. **Any new filter you
ask for must state which of the three it means.**

### 5.4 Live counts are mandatory

Every option carries its own count, computed with every *other* active filter applied but not the
facet's own, which is what makes a multi-select behave sensibly (`build_filter_where(args, skip=key)`).
The spec argues for this with a worked collapse that has since been used as a verification target:

| Stack | Companies |
|---|---|
| Active | 1,409,284 |
| + segment Small | 374,875 |
| + outstanding mortgages > 0 | 53,086 |
| + former LBG | 2,807 |
| + competitor entered 12m | 56 |
| + won a contract in 12m | **0** |

> Without counts, users build empty queries and conclude the tool is broken.

The first five steps reproduce exactly. The sixth cannot be reproduced, because contract activity is
not a filter, which is the same gap as section 7.

`EAGER_FACETS` lists the 22 facets counted on every repaint. `region` and `industry` are excluded on
purpose (175 and 727 options) and served by `/api/options` as typeahead instead. Range filters carry
no option list, only bounds.

### 5.5 Views

Three named starting populations, in `VIEWS`:

```python
VIEWS = {"all": "TRUE",
         "gazette": "gaz_matched = 1",
         "lbg": "ever_lbg_client AND NOT is_lbg_client"}
```

Filters always apply **inside** the selected view. Each view also carries its own default ordering
(`/api/browse`): `all` by name, `gazette` by `gaz_max_distress_stage DESC, gaz_latest_notice_date
DESC`, `lbg` by `months_since_last_lbg_satisfaction ASC`.

### 5.6 Sorting, and the defect that makes the tie-break non-negotiable

`TIE_BREAK = ", CompanyNumber ASC"` is appended to **every** ordered query. Before it existed, the
Gazette and Former LBG views ordered on non-unique keys and DuckDB's parallel scan arranged ties
differently on each run. Measured: five identical calls to the LBG view returned **five different sets
of companies**; walking six pages of 100 showed **526 distinct companies in 600 slots, so 74 were
never displayed**; and growing the list from 25 to 50 moved 15 of the 25 visible rows on screen.

`CompanyNumber` is unique across all 1,531,094 rows and never null, so appending it makes every sort a
total order. It is always ASC: the tie-break only has to be stable, and flipping it with the primary
key would make ties jump when the user changes direction. **The lesson generalises: an ordering that is
merely correct is not enough, it has to be total, or pagination quietly lies.** Any new ordered
endpoint must carry it.

Custom sort is gated on `SORTABLE` (the numeric allow-list plus `CompanyName`, `CompanyNumber`,
`gaz_latest_notice_date`), always `NULLS LAST` so unscored companies never head a ranked list.

### 5.7 Filters fail closed

Unrecognised values used to be silently dropped, and the failure **widened** the result set:
`gazette=not_a_state`, `repayment=bogus`, `preset=not_a_preset` and `view=not_a_view` all returned all
1,531,094 rows, while `segment=NoSuchSegment` correctly returned 0. Same user error, opposite outcomes,
and the dangerous direction: a typo that returns nothing is obvious, a typo that returns everything
looks like a working query. Now a `FilterError` is raised and a 400 handler names the valid options.
`limit` and `offset` are clamped at both ends (a negative limit used to reach DuckDB as `LIMIT -5` and
500); `age_min=nan` and `age_min=abc` both 400 rather than silently returning 0 and everything
respectively.

One silent fallback survives: **`/api/watchlist` still treats an unrecognised view as "gazette"**. It
is not reached by the UI. Worth closing if you are asking for changes near it.

---

## 6. The company profile

`/api/company/<n>` returns a record assembled by `full_record(cn)` (`serve.py:733`). Its docstring is
the thing to remember: the record builders **return exactly the shape `build_data.py` used to bake into
`data.js`**, so the frontend renders an API result with the code it already had. Returning raw Parquet
rows would have meant rewriting every panel.

Blocks on the record: `gazette`, `lender`, `borrowing`, `filing`, `momentum`, `contracts`, `scores`,
`news`, `property`, `trademarks`, `grants`, `timeline`, `sic`, `age_years`, `address`, `incorporated`.
Each is `None` when the company has nothing to say, and each panel function in `index.html` returns
`null` in that case, so a company with no charges does not get an empty borrowing card.

**Percentiles are computed live, not stored.** All four score percentiles come from one scan of the
scored population (`count(*) FILTER (WHERE col > ?)` x4 in a single query). Written first as four
correlated subqueries, that cost eight scans and 900ms per company.

**The timeline** is the thing the original design said would sell the project, and it survived intact:
a Gazette notice, a contract win and a property title in one column in date order, which no individual
notebook can produce. It is assembled by appending to `rec["timeline"]` from each dated source and then
one `sort(key=lambda e: e["date"] or "")`. **Grants are deliberately built after the sort and never
added**, because that source carries no dates at all.

**Render order** in `renderCompany()` (`index.html:3693`): back button, hero, `matchPanel()` ("why this
company is in your list"), then two columns. Left is `leftColumn(c)`. Right is `timelinePanel` (or
`emptyPanel`), then `tiles(c)`, then `evidencePanel` if any timeline entry has an id, then
`[borrowingPanel, propertyPanel, trademarkPanel, grantsPanel, filingPanel, momentumPanel]`, each
skipped when null.

---

## 7. Presets

Nine, in `PRESETS` (`serve.py:~180-243`). Each carries `key`, `label`, `pop` (the verified population),
`retains`, `where` (the definition), `filters` (the same predicate restated in the panel's own
vocabulary), and `note`.

**The redundancy rule:** a preset earns its slot only if it retains **under ~80%** of the population of
its most restrictive single-filter component. Otherwise it is a filter wearing a preset's clothes. Two
failed: "Won public work recently" retained 93.5% and was replaced by "Contract winner with no
borrowing" (2,303), which improved the business logic as a side effect; preset B at 78.2% was tightened
to 63.8% by adding the trading-segment restriction.

**`TRADING = "segment IN ('Micro','Small','Medium','Large')"` is not the same as `is_active`.**
`is_active` is a *status*, `Dormant` is a *segment*, and **89.4% of Dormant-segment companies hold
Active status**. Presets A and H restrict to trading segments; C and D are deliberately left
unrestricted, because a deteriorating exposure or a lapsed client entering administration is more
urgent, not less.

**Presets are adjustable, except one.** Selecting a preset loads its `filters` mapping into the actual
filter controls, so a user can see what it did and change it. The invariant that keeps the two halves
honest: **`where` remains the definition and the count is always computed from `where`, never from the
mapping.** Every mapping was verified by **SET DIFFERENCE in both directions**, not by count, because
two predicates can agree on a total and still select different companies. Eight of nine return 0 and 0.

The ninth is `contract_no_borrowing`, and it is a permanent, documented exception:

| Preset | `where` | expansion | only in `where` | only in expansion |
|---|---|---|---|---|
| contract_no_borrowing | **2,303** | **805,602** | 0 | **803,299** |

Its `contracts_won_12m > 0` condition has no filter control, because contracts are a spine column that
was never approved as a filter. It stays server-side with its four conditions listed as fixed, dashed
chips and the reason stated on screen. **If you ever ask Vishal for a contracts filter, this is the
thing it would unlock, and it would also change the filter system that the verification pass
certified.**

Two measured equivalences worth knowing, both 0 rows of disagreement in each direction:
`lifecycle = Trading` is exactly `is_active`, and `lbg = current` is exactly
`n_lbg_charges_outstanding > 0`.

---

## 8. Sources, and the honesty rules attached to each

Six live: gazette, news, contracts, property, grants, trademark. Zero pending. Hiring was **removed,
not left as an empty tile**: Adzuna returned 401 AUTH_FAIL on every endpoint in August and no usable
data ever reached the dashboard. There are now zero references to hiring anywhere in the code.

| Source | Match | Where it lives | Filterable | On the timeline |
|---|---|---|---|---|
| Gazette | company number | spine (`gaz_*`) + `notices` | **yes**, 10 named states | yes |
| Contracts | company number | spine | **no** | yes |
| Lender / borrowing | company number | spine | yes | no |
| Model scores | n/a | spine | yes (top 1% / top 10%) | no |
| Property | company number | `prop_f` / `prop_e` | no | yes |
| Trade marks | name + postcode **area** | `tm_f` / `tm_e` | no | yes, but every date is 2018 or earlier |
| Grants | name + postcode | `grants` | no | **never**, no dates exist |
| News | cleaned name + corroboration | `news`, `news398` | no | no |

Per-source rules the code enforces and any change must preserve:

- **Gazette temporal decision.** The CH snapshot is 1 July 2026; the Gazette enrichment runs to 31
  July. That is deliberate enrichment, not contradiction, because CH status lags Gazette publication.
  740 companies got their first ever notice in July; **656 are still Active in CH and 586 have never
  been flagged distressed by CH at all**. The condition attached: **if `gaz_*` fields are ever used as
  features in predictive modelling, those 740 are circular and must be excluded via
  `gaz_new_in_july_flag = 1`.** The dashboard correctly does not apply that exclusion, because it
  describes rather than predicts.
- **Property trustee threshold = 30** (99th percentile rounded up, 680 of 60,629 companies above it).
  Holdings run median 1, p90 4, p99 29, max **65,556**, and the long tail is trust and
  corporate-services firms holding titles for clients. **The true count is always shown and never
  altered**; above the threshold the page adds an explanation. Nothing is hidden to make the number
  look sensible.
- **Trade mark vintage is a hard stop, not a lag.** The IPO published its free bulk extract on 13
  February 2018 covering the register to **28 January 2018** and has never updated it. So
  `tm_count_12m` is 0 for all 15,713 companies and is never displayed; `tm_days_since_latest` averages
  5,596 days and is never displayed as recency; status is as-at-2018, so the screen says "registered
  as at" and never "currently holds". Confidence 0.85 on every row, the weakest pack.
- **Grants have no dates and no events file.** `grant_has_date` is 0 on all 10,254 rows, because dates
  live on UKRI project records and reading them would cost ~97,000 API calls. `regNumber` was populated
  on 0 of 500 organisations sampled, so there is no number to join on. Also: 45.3% of UKRI
  organisations publish no postcode and were dropped rather than guessed at, so **"no grant" can mean
  "no match was possible", not "no funding"**.
- **News.** 467 companies searched of 1,531,094 (96 from the stress-test grid plus 398 from the model
  shortlist, of which 27 read `fetch = 'skip'` and stay *unknown* rather than "searched and clean"),
  and **zero verified coverage**. A company carries a `news` block **only if it was actually searched**,
  so absence of the block means unknown, not clean. One row, company `16392251`, is a hardcoded
  exclusion in `NEWS_FALSE_POSITIVES`: it matched an article about Flying Tiger Copenhagen because
  "HOLDINGS" is stripped as a legal suffix leaving the single word TIGER, and the corroborating signal
  was the town LONDON. The handling is the point: **the raw hit is still counted and only the
  verification is reversed**, so the profile can say a hit was found and rejected rather than quietly
  showing nothing. Fifteen companies are in that state.

---

## 9. Scores on the page

Four models, presented under a discipline stricter than the modelling:

| Score | Horizon | Event | Measured hit rate at the top |
|---|---|---|---|
| Lending readiness | 3 months | Takes on new secured borrowing | 43 in 100 |
| Credit risk | 6 months | Hits a genuine insolvency event | 16 in 100 |
| Voluntary exit | 6 months | Has a strike-off proposal filed | not ranked |
| Growth | 12 months | Moves up a size tier | 22 in 100 |

Three rules: shown as **bands, never as probabilities**; the horizon is always visible; scores exist
only for `CompanyStatus = 'Active'` (1,409,284 of 1,531,094) and for the rest the panel disappears with
a reason rather than showing zeros.

**Voluntary exit is deliberately not offered as a filter**, because 998 of its top 1,000 values are
exact ties and the top-100 cutoff is shared by 139 companies. It cannot support a ranked or banded
filter. It still appears on a company page, where a band is a fact about one company rather than an
invitation to sort a list by it. This is the dashboard honouring NB17's finding directly.

---

## 10. The frontend, in the shape you need to instruct changes

`dashboard/index.html`, 4,462 lines: `<style>` to line 1906, markup, then one `<script>` from 2066.
**Zero dependencies, zero build step.** Fonts are two self-hosted `.woff2` files in `dashboard/assets/`.

Key objects:

- **`API`** (line 2253): thin `fetch` wrappers, one per endpoint.
- **`FSTATE`** (line 2281): the single source of truth for the panel, the preset chips and the result
  list. `{view, preset, fromPreset, beforePreset, values, shown, lastApplied, open}`. `preset` is a
  server-side clause; `fromPreset` is a preset loaded *into* the controls and therefore adjustable; a
  preset is one or the other, never both. `beforePreset` stores the panel as it stood so removing a
  preset restores what the user had.
- **`fparams(extra)`** (2297): serialises `FSTATE` into the query string every endpoint takes. This is
  why view, filters and preset are shared by `/api/browse`, `/api/filters` and `/api/options` without
  any of them knowing about each other.
- **`PAGES`** (3026): `[["home","Home",()=>renderLanding()], ["analytics","Analytics",()=>renderMarket()]]`.
  `paintNav()` draws the nav from this array. **This is the whole page router.** There is no URL
  routing at all, which is a stated limitation: navigation never changes the address bar, browser Back
  leaves the dashboard, and nothing is deep-linkable.
- **`SOURCES`** (2330): the six tiles, `{key, label, colour, icon}`, with `live` set at boot from
  `META.sources_live` rather than hardcoded, because when the list was independent the two drifted and
  the page kept claiming one source after a second was connected.
- **`sourceState(c, s)`** (4214): one branch per source key, returning `{state, checked, val, sub,
  detail}` where `state` is `on` / `off` / `wait`. This is where "checked, nothing found" and "not
  searched" are kept apart.
- **`filterControl(f)`** (3413): renders one filter from the `/api/filters` payload, per `kind`. Adding
  a filter server-side needs no frontend change unless it needs a new `kind`.
- **`refresh()`** (3302) / **`paintPanel()`** (3494) / **`paintRows()`** (3515): the repaint cycle.
- **`renderMarket()`** (2756) plus `maCard`, `mktBars`, `mktHeat`, `mktCurve`, `mktKpi`: the Analytics
  page, eleven figures rebuilt as native HTML/CSS/SVG rather than pasted notebook images. **Analytics
  does not respond to the Home filters**, deliberately: it always describes the whole market, because a
  page that silently re-scoped itself would make it impossible to tell whether a number was about the
  market or about a filtered slice.

Two interface reversals worth knowing before asking for visual changes. The glass/refraction treatment
(an SVG displacement filter inside `backdrop-filter`, Chromium only, capability-probed onto an
attribute on `<html>`) is applied to **navigation and controls only and deliberately not to analytical
cards**, on the reasoning that a page where everything is glass has no hierarchy. And a full
Three.js/GLSL liquid-glass effect was investigated and rejected on a specific technical ground: the
shader samples its background from a WebGL render target, and there is no supported way to rasterise
live DOM into a WebGL texture (`html2canvas` does not support `backdrop-filter`, which this page uses
on nearly every surface).

---

## 11. Recipes: how to actually change it

These are written so you can hand one to Vishal, or to another agent, as a spec.

### 11.1 Add a new source that only shows on a company page (a CSV, name- or number-keyed)

This is the cheap path and it is what property, trade marks and grants did.

1. Ship two CSVs in the agreed shape: `<source>_company_features.csv` (one row per company, for the
   tile and panel) and `<source>_events.csv` (one row per event, for the timeline), both carrying
   `CompanyNumber`, and events carrying `event_date, event_type, detail, value, url, confidence,
   match_method`. If the source has no dates, ship only the features file and say so, like grants.
2. `serve.py :: load_aux()` -> add a `CREATE TABLE <name> AS SELECT *, {CLEAN_CN...} AS cn FROM
   read_csv(...)`, and add the table name to the row-count print loop.
3. `serve.py :: full_record()` -> add a `q("SELECT * FROM <name> WHERE cn = ?", [cn])` block that sets
   `rec["<source>"]` (or `None`), and, **if and only if the source has real dates**, append to
   `rec["timeline"]` before the sort.
4. `serve.py :: meta()` -> add the source key to `sources_live` and add its count/as-of block, so the
   tile can state its vintage.
5. `index.html` -> add an entry to `SOURCES`, add a branch to `sourceState()`, write a
   `<source>Panel(c)` returning `null` when empty, and add it to the panel array in `renderCompany()`.

Non-negotiables: a **vintage/as-of date** for the source, a **confidence and match method** carried
through to the screen if the match is anything other than an exact company number, and a
**"not searched" state distinct from "searched, found nothing"** if the source only covered a sample.

### 11.2 Make a source filterable

Side tables cannot be filtered. There are exactly two options and it is worth being explicit with
Vishal about which one you want:

- **The right way: put the column on the spine.** Aggregate the source to one row per company, join it
  into `dashboard_bulk_gazette_2026-07.parquet` the way `notebooks/13_merge_bulk_gazette.ipynb` joined
  the 55 `gaz_` columns, and re-export. Then it is a normal column and 11.3 applies.
- **The expensive way:** teach `build_filter_where` to emit a subquery against a side table
  (`CompanyNumber IN (SELECT cn FROM prop_f WHERE ...)`). Nothing in the codebase does this today, the
  facet-count path would need the same treatment, and the performance claims in section 17 of
  `dashboard_design.md` were not measured against it. Do not ask for this casually.

### 11.3 Add a filter on an existing spine column

1. Add one entry to `FILTERS` with `group`, `label`, `kind`, and `col` or `expr` or `choices`. If the
   column has NULLs, decide explicitly whether it is `tri` or a `nullable` `choice` with `null_col`,
   and state what NULL means.
2. Add the key to `EAGER_FACETS` if it should carry live counts (do **not** if it has hundreds of
   options; make it a `/api/options` typeahead instead, like region and industry).
3. Add display labels to `CHOICE_LABELS` if it is a `choice`, or the options render as raw keys.
4. Nothing else. The panel, the WHERE builder and the facet counts all read the same entry, and the
   frontend renders whatever `/api/filters` describes.

### 11.4 Add a preset

1. Append to `PRESETS` with `where` (the definition), `filters` (the same thing in panel vocabulary),
   `pop`, `retains`, `note`.
2. **Check the redundancy rule:** it must retain under ~80% of its most restrictive single-filter
   component, or it is a filter, not a preset.
3. **Verify the mapping by SET DIFFERENCE in both directions**, not by count. If it cannot be expressed
   in existing controls, set `filters=None` and supply `not_adjustable` and a `conditions` list, the
   way `contract_no_borrowing` does, so the screen can say it cannot be taken apart and why.

### 11.5 Add a sort option

Add the column to `SORTABLE`. It will automatically get `NULLS LAST` and the `CompanyNumber` tie-break.
Do not add an ordered query anywhere without `TIE_BREAK`.

### 11.6 Add a view

Add one entry to `VIEWS` with its predicate, and a default `ORDER BY` in `/api/browse` (and
`/api/watchlist` if it belongs on the landing page). Add a label to `VIEW_LABEL` in `index.html`. Views
are starting populations, not filters: filters apply inside them.

### 11.7 Add a page

Append `["key", "Label", () => renderThing()]` to `PAGES` in `index.html` and write `renderThing()` to
clear `app` and append sections. If it needs its own data, add a `/api/<thing>` endpoint and an `API`
wrapper. If it is a fixed report rather than a live query surface, cache it the way `/api/market` does.
Decide explicitly whether it responds to the Home filters; Analytics deliberately does not.

### 11.8 Wire the model scores from a different run

They are already wired: `score_lending`, `score_insolvency`, `score_voluntary_exit`, `score_growth`
are spine columns from run `refactor_growthfix`, and the chronology's "the two halves of this project
have been one join apart for two weeks" is **closed**. To change run, rebuild the Parquet from the
relevant `data/processed/scores/scores_<tag>_2026-07.parquet` via
`notebooks/20_dashboard_handover.ipynb` and restart the server; the quantiles recompute at startup.

---

## 12. What is proven, and what is not

**Proven, by an adversarial pass on 19 August whose ground truth was written independently from column
semantics rather than copied from `serve.py`, roughly 400 assertions:**

- **Filtering came through clean.** 63 facet counts, 34 filter cases, 9 presets decomposed into 36
  conditions, 22 hand-built combinations including 8 deliberate contradictions, 120 seeded random
  combinations. Zero count mismatches, zero rows failing the predicate they were selected by. Every
  injection attempt returned 0 rows.
- **Presets:** verified by set difference both directions; 8 of 9 return 0 and 0, the ninth documented
  with its exact divergence.
- **Ordering:** 10 identical calls per view return identical rows; page walks of 300 to 600 slots show
  zero duplicates and zero skipped companies; four pages of 25 equal one call for 100.
- **Analytics:** every displayed figure checked against Sneha's CSVs, the notebook output, and an
  independent recomputation from the Parquet.
- **Performance:** ~57 aggregate queries per full panel repaint at 0.58s cold; `/api/presets`
  recomputes nine populations over 1.5M rows in 0.17s.

Five defects were found, and **none of them were in the filtering**: B1 non-deterministic ordering
(section 5.6), B2 negative limit 500, B3 filters failing open (5.7), B4 range inputs failing open and
closed inconsistently, B5 the genuine severity tier `'none'` on 27 companies being scrubbed by the
shared `_txt()` null-marker helper, fixed with a narrow `_cat()` used for `gaz_severity_tier` only.
Three more were found after the spec closed: two frozen animations (a `transform` transition on an
unpromoted element sitting behind a 1-2s `refresh()`, fixed with `will-change: transform`, first
movement went from "never within 1.3s" to "1ms"), a stray `}` in the stylesheet that Chromium recovers
from by consuming the next rule (it ate the `@supports` no-backdrop-filter fallback for a long time,
then ate the intro overlay's full-screen curtain rule), and `brand()` probing two logo files that never
existed, logging two 404s on every page load.

**Not proven / not in any repository file:** the three-stage architecture history and the
DuckDB-vs-PyArrow benchmark in section 1 come from Vishal's working record only, and the sharded build
no longer exists on disk to inspect. One number in that record does not reconcile: the shard design is
described as ~15,000 companies per shard, but 105,078 across 100 shards is closer to 1,050. The precise
reason hiring produced no usable data is recorded only as "pending and never landed"; Samuel's
`reports/adzuna-limitation.md` supplies the missing half (uniform 401 AUTH_FAIL, an `app_id` measuring
9 characters where Adzuna issues 8).

---

## 13. Limitations to state before asking for anything

1. **Contracts cannot be filtered**, which is why one preset can never be taken apart.
2. **The lender block has no as-of date and no staleness flag**, unlike the Gazette and contracts
   blocks, so its currency cannot be checked from the file. This is a fix at source, not in the
   dashboard, and it is the gap behind the whole ANTALIS investigation (section 14).
3. **Three sources are name-matched**, not number-matched: grants and trade marks on name plus postcode
   area, news on cleaned name. Trade marks are confidence 0.85 across all 15,713 rows and the register
   is eight years old.
4. **News contributes almost nothing**: 467 searched, zero verified. A finding, not a defect.
5. **No URL routing.** Nothing is deep-linkable and browser Back leaves the dashboard.
6. **`/api/watchlist` still silently falls back to the gazette view** on an unrecognised value.
7. **`store_meta.json` is stale on one field:** it still lists `sources_live` as gazette/news/contracts
   and four pending. `/api/meta` overrides both lists from what `load_aux()` actually read, so the
   screen is right, but do not read the JSON file as the source of truth.
8. **`data.js` and `build_data.py` are Design-2 residue.** The 27MB file is gitignored and not on the
   branch; `store_meta.json` replaced its only remaining job.
9. **`gaz_new_in_july_flag` has not been applied anywhere**, correctly, and must be honoured before any
   `gaz_*` field is used as a model feature.

---

## 14. The one investigation to read before you touch preset A

This is the most valuable thing in Vishal's record, because it is the project catching itself being
wrong about something it had already decided, and it is a direct warning about the lender columns.

Preset A tested `debt_ratio = 0`. Cross-verifying a move to `Mortgages.NumMortOutstanding = 0` turned
up exactly one company of difference: **ANTALIS LIMITED, 01088345**, 416 charges, 2 still outstanding,
true ratio 0.0048, and `debt_ratio` is rounded to 2dp upstream so it stores as 0.00. It is the only
company in the file whose ratio falls in the 0 to 0.005 band. Preset A moved, 31,003 -> 31,002.

The cross-check then uncovered something bigger: **the file carries two different "outstanding"
measures and they disagree.** `Mortgages.NumMortOutstanding` is the Companies House bulk count;
`n_charges_outstanding` is the charge-level lender pipeline. They differ on 2,859 companies, and on
1,300 of those one is zero while the other is not. Every lender field is built on the pipeline column,
which produces **996 companies where the bulk says nothing is outstanding but a named lender is
attached**. Inside preset A, a list whose entire promise is "no incumbent to displace", that left 661
companies carrying a named lender, 118 of them current LBG clients.

**The first conclusion was that this was a business error, and it was wrong.** The disagreement is a
function of **company age**, not data freshness:

| Company age | Pipeline says outstanding | Bulk disagrees | Rate |
|---|---|---|---|
| under 10y | 20,592 | 21 | **0.10%** |
| 10-20y | 30,298 | 49 | 0.16% |
| 20-30y | 26,988 | 70 | 0.26% |
| 30-50y | 18,112 | 442 | 2.44% |
| **50y+** | 7,549 | 701 | **9.29%** |

A ninety-fold gradient. Disputed LBG relationships carry an average charge age of **34.4 years** against
12.9 where the sources agree; **88 of 173 have no satisfaction record at all**; of the 118 current LBG
clients inside preset A, 86 hold a charge over 30 years old and only **4 hold one under 10 years**. The
17 companies disagreeing the other way show no age gradient and are noise. That is the signature of
**charges left open on the register because a satisfaction was never filed**, not of live secured
borrowing: the pipeline's gate holds a charge open whenever the satisfaction date is missing, which is
exactly the condition expected on a 1980s charge. Two alternatives were ruled out: it is not
jurisdictional (England and Wales disagrees *more* than Scotland or Northern Ireland), and the bulk is
not flawless either (its own three counts fail to reconcile on 463 companies, and on 41 the pipeline
sees more outstanding charges than the bulk records as ever having existed).

**Decision: preset A stays on `Mortgages.NumMortOutstanding = 0`.** The recommended change would have
taken it from 31,002 to 30,163, and *"that would delete real prospects to fix a phantom."* The record
is also honest that charge age is measurable only for the LBG subset, because that is the only
charge-date column in the file, so for the other 543 lendered companies the live-versus-stale split is
inferred from the gradient rather than measured.

Three lessons, and they generalise past this dashboard: **a number that looks like an error can be the
data telling you about the world**; **provenance beats plausibility**, the two columns were compared on
where they came from and how they were gated rather than on which gave the more comfortable answer; and
**a gap got recorded rather than papered over**.

---

## 15. Where to look for what

| Question | File |
|---|---|
| How do I use it? | `dashboard/dashboard_handbook.md` (+ 10 screenshots in `dashboard/handbook_img/`, PDF alongside) |
| Why is it built this way? | `dashboard/dashboard_design.md` |
| What does each filter/preset mean, and what went wrong? | `dashboard/FILTER_SPEC.md` (the decision and error log, richer than either) |
| What is in the Parquet, column by column? | `dashboard/dashboard_handover_columns.md` (= `reports/dashboard_handover_columns.md` on `sneha-viktor/shap`) |
| The original plan the architecture abandoned | `reports/integration-design.md`, `notebooks/nb11_blueprint.ipynb` |
| Gazette feature definitions | `reports/nb10_gazette_feature_catalogue.md` |
| How the Parquet was built | `notebooks/20_dashboard_handover.ipynb` (Viktor), `notebooks/13_merge_bulk_gazette.ipynb` (Vishal) |
| Samuel's three packs | `reports/dashboard-pack.md`, `reports/adzuna-limitation.md` on `samuel/spine-crosswalk` |
| The server | `dashboard/serve.py` |
| The page | `dashboard/index.html` |
| Legacy static build | `dashboard/build_data.py`, `dashboard/store_meta.json` |
