# Companies House Data Store: the manual

A plain-language guide to what the dashboard is, what it is made of, how to start it, and how it
works. Written to be read start to finish in about fifteen minutes.

Snapshot: July 2026. Universe: 1,531,094 companies. Prototype, not a live system.

---

## 1. What it is, in five lines

- A search-and-filter tool over every active UK company in our three target sectors.
- It joins six public sources onto one spine, using the company number as the key.
- It shows four model scores per company, each with the reasons behind it.
- It runs entirely on your own machine. Nothing is sent anywhere.
- It does not make lending decisions. It shortlists companies worth a conversation.

---

## 2. What it is built from

**Languages**

- **Python** for the server (`dashboard/serve.py`, about 2,000 lines).
- **HTML, CSS and JavaScript** for the screen (`dashboard/index.html`, about 5,100 lines).

**Libraries, and that is the whole list**

| Thing | What it does |
|---|---|
| **Flask** | The web server. Answers requests from the browser. |
| **DuckDB** | The query engine. Reads the parquet file and does the counting. |
| **pandas** | Moves query results around inside the server. |

**What it deliberately does not use**

- **No JavaScript framework.** No React, no Vue, no jQuery. The screen is plain JavaScript, so there
  is no build step and nothing to install for the front end.
- **No external files at runtime.** No CDN, no Google Fonts, no analytics. The fonts ship in
  `dashboard/assets/`.
- **No database.** DuckDB reads the parquet file where it sits. No `.db` file is ever created.
- **No internet.** The server makes no outbound calls. Every API result was collected earlier and
  saved to disk. You can run the whole thing on a plane.

---

## 3. How to start it

**Step 1.** Clone the repository and install the dependencies:

```
git clone https://github.com/Viklin41/lloyds-commercial-banking-intelligence-2026.git
cd lloyds-commercial-banking-intelligence-2026
pip install -r requirements.txt
```

The dashboard itself needs only three packages, so `pip install Flask duckdb pandas`
is enough if you do not intend to run the notebooks.

**Step 2.** Fetch the data. It is 217 MB and is not in git, so it ships as a release
asset:

```
python scripts/fetch_dashboard_data.py
```

This downloads the bundle and unpacks the 15 files into `data/`, in the layout the
server expects. If you already have `Data_Dashboard.zip`, skip the download with
`--zip PATH`.

**Step 3.** Run the server:

```
python dashboard/serve.py
```

It opens `http://127.0.0.1:8000` in your browser by itself after about a second.

**What you should see in the terminal.** If you see this, it worked:

```
data    : .../lloyds-commercial-banking-intelligence-2026/data
parquet : .../data/processed/dashboard_bulk_gazette_2026-07.parquet
universe: 1,531,094 companies queryable
loading side tables ...
  notices    291,045 rows
  news            96 rows
  news398        398 rows
  grants      10,254 rows
  tm_f        15,713 rows
  ...
  score thresholds computed (lending p99 = 0.053406)
serving : http://127.0.0.1:8000   (Ctrl+C to stop)
```

**To stop it:** Ctrl+C in that terminal.

**Useful flags**

| Flag | What it does |
|---|---|
| `--no-browser` | Start without opening a browser tab. |
| `--port 8080` | Use a different port if 8000 is busy. |
| `--data DIR` | Point at a different copy of the data tree. |

---

## 4. Where the data lives

This matters, because **the data is not in the repository**. The files are far too
large to commit, so they are published as a release asset instead.

- **The code** is in the git repo, under `dashboard/`.
- **The data** is downloaded into `data/` by `scripts/fetch_dashboard_data.py`, and
  `data/` is gitignored.

The server finds the data in three steps, in this order:

1. The `--data` flag, if you passed one.
2. The `LLOYDS_DATA` environment variable, if it is set.
3. Otherwise `data/` beside the repository, which is where the fetch script puts it.

If it cannot find the files it prints the paths it tried and stops, rather than
starting up empty.

**The files it reads**

| File | What it holds |
|---|---|
| `dashboard_bulk_gazette_2026-07.parquet` | **The spine.** One row per company, 1,531,094 rows, 124 columns. Everything else hangs off this. |
| `nb10_gazette_notices_thru_2026-07.csv` | 291,045 insolvency notices |
| `land_registry_company_features.csv` + events | Property, 60,629 companies |
| `ipo_trademarks_company_features.csv` + events | Trade marks, 15,713 companies |
| `ukri_grants_company_features.csv` | Grants, 10,254 companies |
| `nb14_news_signals_2026-06-30.csv` | News search results, 96 companies |
| `identity_2026-08-01.parquet` | Address and incorporation date |
| `mi_*_2026-07.csv` | The three market-analysis outputs behind the Analytics page |
| `shortlist_reasons_2026-07.parquet` | SHAP reasons. Also committed in the repo, in `dashboard/post_build_change/`, and read from there if the data copy is absent |

---

## 5. How it actually works, one request at a time

This is the whole architecture. There are only four moving parts.

1. **You type something.** The browser sends a request, for example
   `GET /api/browse?view=all&segment=Small&lending=top1`
2. **Flask receives it** in `serve.py` and checks every value against an allow-list. Anything it does
   not recognise is rejected, never passed through to the database.
3. **DuckDB runs one SQL query** straight against the parquet file. It reads only the columns and rows
   needed, not the whole file.
4. **The server sends back JSON**, at most 500 rows. The browser draws it.

**The key idea.** Earlier versions tried to send the whole dataset to the browser, which meant only
105,078 companies with signals could be included. Querying the file in place instead made all
1,531,094 addressable, and the page loads in the same time either way, because the browser only ever
receives one screen's worth.

**Why DuckDB.** It was measured against PyArrow on the same aggregations and was nine times faster.

**Why it is safe.** Every value from the URL goes into the query as a bound parameter, never pasted
into the SQL text. Every column name is checked against a fixed list. Typing SQL into the search box
does nothing.

---

## 6. What each screen does

### Home

- **Search box.** Type a company name or number. Matches on both.
- **Views.** Four starting populations: all companies, those carrying a Gazette signal, former Lloyds
  clients, and the model rankings.
- **Presets.** Nine saved queries for recurring commercial questions.
- **Advanced filters.** 27 filters in six groups (Core, Borrowing, Lender, Filing, Momentum, Signals).
- **Results.** The matching companies, 25 at a time.

**Two things worth knowing about the filters:**

- **Every option shows its live count**, recalculated as you build the query, so you can see an option
  is empty before you pick it.
- **"No" and "Not stated" are different things.** A blank lender field means no outstanding charge,
  not "no banking relationship". The filters keep those apart rather than treating missing as false.

### Presets

- Each one is a combination that was tested to return a useful population.
- **Picking one loads its conditions into the filter panel**, so you can see exactly what it did and
  change any part of it. Nothing is hidden.
- One exception: "Contract winner with no borrowing" cannot be taken apart, because contract activity
  has no filter control. The screen says so.

### Company profile

- Identity header, then a bar telling you **why this company is in your list**.
- Panels: model scores, Gazette assessment, lender relationship, borrowing, filing health, and what
  changed in the last twelve months.
- **One timeline** merging Gazette notices, property titles and trade marks in date order.
- **Source tiles** distinguish "we looked and found nothing" from "we never looked". Those are
  different statements and the screen never blurs them.

### Model rankings

- The **top 100 companies on each model**, with numbered positions.
- A curve showing how fast the score falls from #1 to #100, so you can see whether position carries
  information.
- A composition read: who already lends to those hundred.
- Covers three models. Voluntary exit is excluded, see the FAQ.

### Analytics

- A market-level view, not another company list. It does not respond to filters.
- Lloyds' position in UK secured lending: the league table, concentration, sector and size patterns,
  our own book, and where lapsed clients went.

---

## 7. The four model scores

- Built with **LightGBM** (gradient-boosted decision trees).
- Trained on **33 monthly snapshots** of the register, October 2023 to July 2026.
- Features come from month `t`, labels from `t+1` onwards. **The model never sees its own answer.**
- Scored for the **1,409,284 active companies** only. A company in liquidation gets no score, and the
  screen says "not scored" rather than showing a zero.

| Score | Window | What it predicts | Right in top 100 | Base rate | Lift |
|---|---|---|---|---|---|
| Lending readiness | 3 months | Registers a new charge | 41 to 43 | 0.26% | ~150x |
| Credit risk | 6 months | Hits a genuine insolvency event | 14 to 16 | 0.33% | ~45x |
| Growth | 12 months | Moves up a size tier | 22 | 2.1% | ~10x |
| Voluntary exit | 6 months | A strike-off proposal is filed | 78 to 85 | 7.2 to 8.2% | ~10x |

**Read the lift, not the hit rate.** Voluntary exit looks like the best of the four and is the
weakest: about one company in twelve files for strike-off anyway, so a random list would be right
most of the time. Lending readiness at 41 in 100 against an event that happens to one company in 400
is the strong result.

**SHAP reasons.** Where a company is in the top 5,000 on a model, the profile names the three
features that moved its score most and by how much. About 0.35% of the scored population carries
these, so most companies show "no SHAP analysis available". That is coverage, not a finding about
the company.

---

## 8. The six sources, and what each is worth

| Source | Joins on | Companies | What it tells you | The catch |
|---|---|---|---|---|
| **Gazette** | company number in the notice text | 19,525 | Insolvency notices, dated | Only fires after the failure. 75% of already-insolvent companies, 0.075% of trading ones |
| **Land Registry** | company number | 60,629 | Property owned | Widest reach of any source we found |
| **Contracts** | company number | 15,517 | Public contract wins | As at 31 May 2026, two months behind the register |
| **Trade marks** | name + postcode area | 15,713 | Brands registered | **The register stops at 28 Jan 2018.** The IPO has never updated its free file |
| **Grants** | name + postcode | 10,254 | UKRI research funding | Carries no dates, so it cannot go on the timeline |
| **News** | name only | 0 verified | Nothing | Measured zero. See the FAQ |

**The one line that explains that whole table:** if a source prints the company number, it works. If
it only prints a name, it does not.

---

## 9. Companies to search in a demo

All verified against the July 2026 file. Type the name into the search box.

### The best all-round example

| Company | Number | Why |
|---|---|---|
| **CUBICLE WASHROOM SYSTEMS LIMITED** | 09919041 | The whole story on one page. Small Hampshire manufacturer, 10 years old. Former Lloyds client who left for **NatWest**, a rival took a charge within 6 months, borrowed twice in the last year, and won its **first public contract, £597k**. Ranked **499th of 1,409,284** on lending readiness, with SHAP reasons showing why. |

### For each panel

| To show | Company | Number | What you get |
|---|---|---|---|
| **Gazette timeline** | PURITY LTD | 11975958 | 7 notices, petition through to creditors' meetings, all linked. Also shows "not scored" for a liquidated company |
| **Gazette, still trading** | GOWER STREET ANALYTICS LTD | 09455007 | 4 notices but still Active: distress before failure |
| **Most property** | NATIONAL HIGHWAYS LIMITED | 09346363 | 65,556 titles. Shows the large-holder caveat the screen adds above 30 |
| **Most trade marks** | UNILEVER PLC | 00041424 | 4,174 marks, and the 2018 vintage label |
| **Most grants** | JOHN INNES CENTRE | 00511709 | 843 UKRI projects |
| **Four sources at once** | GOONHILLY EARTH STATION LIMITED | 06896077 | Property, 3 trade marks, 6 grants and a £2.15m contract on one profile |
| **Four sources, SME** | EARTHSENSE SYSTEMS LIMITED | 10272221 | Property, 4 marks, 5 grants, a contract, plus SHAP reasons |
| **SHAP on three models** | DUAL SEAL GLASS LTD. | 03036278 | Reasons on lending, growth and credit risk at once. Also a former Lloyds client, now with NatWest |
| **Current Lloyds client** | ARAPRINT LIMITED | 02240299 | Small manufacturer, 26 of 29 charges ours (90% share), one rival present, 14 property titles |
| **Lapsed client, and the richest profile** | PARK CAKES LIMITED | 05998327 | Left us, now banks with **HSBC**, 24 charges outstanding. Also carries property, trade marks, grants **and** SHAP reasons on lending, so nearly every panel is populated at once |
| **Empty state** | !NFOGENIE LTD | 13522064 | Nothing found anywhere. Shows how absence is reported |

### Top of each ranking

| Model | #1 | Number |
|---|---|---|
| Lending readiness | MS LENDING GROUP LIMITED | 12723324 |
| Credit risk | APOIDEA SOLUTIONS LIMITED | 09654369 |
| Growth | ADVANCED INSTRUMENTS LTD. | 07284911 |

**Get in front of this one.** The #1 lending company, MS Lending Group, is itself a bridging lender:
its 578 charges are its loan book, not its borrowing. Say so before someone asks. It is a real
property of the model, that the strongest predictor of who borrows next is who has borrowed before,
and it is written up in the report.

---

## 10. Questions you may be asked

**Is this using Lloyds customer data?**
No. Every field came from Companies House, the Land Registry, the Gazette, Contracts Finder, the IPO
and UKRI. All free, all public. No internal data was ever available to us.

**How accurate is it?**
Of the top 100 for lending readiness, 41 to 43 went on to register a new charge, measured on two
months held back from training. The event happens to about 1 company in 400, so that is roughly 150
times better than picking at random.

**Is the score a probability?**
It is a probability-scaled score, corrected back to the true base rate. It tracks well through the
middle of the range. At the very top there are too few past cases to check it, so read the band
rather than the digits. The panel says this on screen.

**Why is voluntary exit not ranked?**
Its top 1,000 scores contain only 14 distinct values, and 138 companies are tied on the score sitting
in 100th place. A numbered top 100 would be inventing an order the data does not have, so it ships as
a band instead.

**Why did the news data find nothing?**
We tested it twice. On the 398 companies our own models ranked highest, 10 had any hit at all and
none survived checking. A control search for Tesco returned 147 articles, so the tool worked.
Companies this size are simply not written about. Nine of the ten hits were name collisions, one
being a company called Tiger Holdings matching a story about Flying Tiger Copenhagen.

**Why is the trade mark data from 2018?**
The Intellectual Property Office published a free bulk extract in February 2018 and has never updated
it. That is a property of the source, not of our collection. Every number from it carries the date on
screen.

**Can it cover the whole register, not just three sectors?**
Yes. The sector filter is a scope decision, not a technical limit. The pipeline does not care.

**How current is it?**
The register snapshot is July 2026. Contracts are as at 31 May, property 29 June, trade marks January
2018. Every one of those dates is printed next to the number it belongs to.

**How do you know the filters are right?**
They were verified against independently written SQL, not against the implementation: 63 facet counts
and 120 seeded random filter combinations, with no count mismatches. The nine presets were checked by
set difference in both directions rather than by count, because two different queries can return the
same total and still select different companies.

**What happens if a company has no data?**
The profile says which sources were checked and found nothing, separately from which were never
searched. Absence is reported, never dressed up as zero.

**Does it tell you who to lend to?**
No. It shortlists companies that may be worth a conversation. The credit decision stays with the
banker, and nothing in the dashboard is a recommendation.

**What is the weakest part?**
Three things, honestly. The lending model largely finds companies that already borrow heavily. The
growth model leans on current size, because the target is moving up a size tier. And a registered
charge is a proxy for a banking relationship, not the relationship itself: it says nothing about
current accounts, deposits or unsecured lending.

---

## 11. If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| "Query server not running" on screen | The server stopped | Restart it, then reload the page |
| `ModuleNotFoundError: duckdb` | Dependencies not installed | `pip install Flask duckdb pandas` |
| "Could not find the company parquet" | Data not fetched, or tree moved | Run `python scripts/fetch_dashboard_data.py`, or pass `--data` |
| Port already in use | Something else on 8000 | `--port 8080` |
| Analytics is slow the first time | It computes once, then caches | Load it once before a demo |
| A search finds nothing | It matches name and number, not partial words mid-name | Try fewer words, or the company number |

---

## 12. Where to read more

- **`dashboard_handbook.md`**: what every filter, preset and panel does, in detail.
- **`dashboard_design.md`**: why it was built this way, what testing broke, and what we can prove.
- **`FILTER_SPEC.md`**: every filter, its exact SQL, and how it was verified.
- **`POST_BUILD_CHANGES.md`**: what changed after the specification closed.
- **`../reports/dashboard_handover_columns.md`**: every column on the spine parquet,
  what it means, and the three that are easy to misread.
