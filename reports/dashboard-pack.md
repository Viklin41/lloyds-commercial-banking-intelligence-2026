# Dashboard pack: property, trade marks, grants

**Samuel, 11 August 2026.** Three public sources matched to the universe in
`company_master_gazette_thru_2026-07.csv`, 1,493,972 companies. Join on `CompanyNumber`,
cleaned the same way on both sides.

## What is here

| Source | Companies | Share of universe | Events | Match |
|---|---|---|---|---|
| Land Registry property | **60,629** | 4.06% | 318,068 | company number |
| IPO trade marks | **15,713** | 1.05% | 93,795 | name + postcode area |
| UKRI grants | **10,254** | 0.69% | none, see below | name + postcode |
| Guardian news | **0** | 0.00% | none | name + corroboration |
| Adzuna hiring | not collected | | | see ADZUNA_LIMITATION.md |
| **Any of the three that worked** | **78,782** | **5.27%** | | |

For comparison the Gazette layer reaches 19,814 companies, 1.33%. These three together
reach four times as many.

773 companies carry all three, 6,268 carry two.

## Files

Each source ships the same three files, matching the pattern of the Gazette work:

```
<source>_events.csv             one row per event, for the timeline
<source>_company_features.csv   one row per company, for the tiles
<source>_signals.csv            the same events in the agreed eight column shape
```

Grants ship only a features file, because there is no date. See below.

Event columns: `CompanyNumber, event_date, event_type, detail, value, url, confidence,
match_method`, plus source specific extras.

## The three vintages, which are not the same

This matters more than anything else in the pack. Stamp each source with its own date.

| Source | Data runs to | Why |
|---|---|---|
| Land Registry | **2026-06-29** | the CCOD file we downloaded |
| IPO trade marks | **2018-01-28** | see below, this is the source, not our download |
| UKRI grants | **2026-08-11** | the day the API was harvested, no history |

Recency windows in the feature files (`_count_12m`, `_days_since_latest`) are measured
against **2026-07-01**.

## Read this before wiring the trade mark tile

**The IPO file stops on 28 January 2018.** The Intellectual Property Office published its
free bulk trade mark data on 13 February 2018 and has never updated it. There is no newer
free file. This is a property of the source, not of our download, and it is checkable on
the gov.uk page.

Practical effects:

- `tm_count_12m` is **zero for every company**. Do not show it.
- `tm_days_since_latest` averages 5,596 days. Do not show it as recency.
- The tile has to carry the vintage, for example "Trade marks, register to Jan 2018",
  or a reader will assume the company stopped filing.

What it can honestly say: this firm was investing in a brand before 2018.

## Read this before wiring the grants tile

Grants have **no date and no events file**, so they can never appear on the timeline.

The UKRI Gateway to Research API returns a name, a postcode and a list of project links per
organisation. Dates live on the project records, which would cost one API call per
organisation, about 97,000 calls. That was out of scope for the deadline.

`regNumber` is present in the API schema but populated on **0 of 500** organisations
sampled, so there is no company number to join on.

Columns: `grant_has_any`, `grant_n_organisations`, `grant_n_projects`,
`grant_match_method`, `grant_max_confidence`, `grant_min_confidence`, `grant_source_date`,
and `grant_has_date` which is always 0 and says so on the row.

## Match confidence, and what to do with it

| Method | Confidence | Used by |
|---|---|---|
| `company_number` | 1.00 | property |
| `name_postcode` | 0.90 | grants |
| `confidence` 0.85 `name_postcode_area` | 0.85 | trade marks |
| `name_postcode_area` | 0.80 | grants, fallback |

Anything below 1.00 is a name match and should be labelled wherever a person sees it.

Rows we could not match are dropped rather than guessed at:

- 45.3% of UKRI organisations publish no postcode, so they are dropped. A name-only match
  is how an Oxford "Amazon Ltd" ends up credited with someone else's work.
- Name plus postcode keys that identify more than one company are dropped, 74 for grants
  and 81 for trade marks.

## Two caveats for the report

**Property has a trustee tail.** The largest holders in our sectors are trust and legal
services companies holding titles on behalf of clients, not on their own balance sheet.
The top one carries 7,266 titles. The median company holds 1 and the mean is 2.2, so this
is a thin tail, but a company page reading "7,266 properties" would be misleading. Cap or
label it.

**Price paid is present on about a third of titles.** Use `prop_value_count` as the
denominator. Never quote `prop_value_total` on its own.

## Findings worth using

Property ownership by sector, which needs no model:

| Sector | With property |
|---|---|
| Manufacturing | 9.80% |
| Technology, legal and professional | 3.47% |
| Fast growth and emerging | 1.65% |

By lifecycle, property ownership is **higher among companies in trouble**: Distressed
29.8% and Insolvent 5.5% against Trading 4.3%. Distressed is only 51 companies of 171, so
treat it as suggestive rather than settled.

Manufacturing leads on all three sources: property 9.80%, trade marks 3.06%, grants 1.41%.

## How these were built

| Script | Does |
|---|---|
| `notebooks/30_property_dashboard_export.ipynb` | Land Registry CCOD |
| `scripts/build_trademark_pack.py` | IPO trade marks |
| `scripts/harvest_ukri_orgs.py` | UKRI API harvest, cached and resumable |
| `scripts/build_grants_pack.py` | UKRI match |
| `src/dashboard_export.py` | shared cleaners and the file writers |

Two bugs in the earlier notebooks were found and fixed on the way, both of which had
stopped these sources producing anything:

- Notebook 09 compared a full Companies House postcode against an IPO postcode area, so it
  matched nothing.
- Notebook 10 called `gtr.ukri.org/api/organisations`, which returns 404. The endpoint is
  `gtr.ukri.org/gtr/api/organisations`.

## Licences to cite

- Land Registry: contains HM Land Registry data, Crown copyright and database right.
- IPO trade marks: Open Government Licence.
- UKRI Gateway to Research: Open Government Licence.


## News: a measured zero, and why there is no news file

`news_coverage_summary.csv` is here. There is no `guardian_news_events.csv`, and that is
deliberate.

The Guardian was searched for all 398 companies the models flagged for July 2026, using the
same method and the same verification rules as the earlier 96-company stress test, so the
two results are comparable. Only the sample changed.

| Stage | n | of 398 |
|---|---|---|
| companies on the shortlist | 398 | 100% |
| searchable, had a name in the universe | 371 | 93.2% |
| any raw hit from the Guardian | 10 | 2.5% |
| raw articles returned | 139 | |
| articles inspected | 112 | |
| articles passing verification | 1 | |
| **genuine matches after review** | **0** | **0.00%** |

**The one article that passed verification was wrong.** Company 16392251, TIGER HOLDINGS
LTD, a London company incorporated in April 2025 with no filings, was matched to an article
about Flying Tiger Copenhagen being acquired by private equity. Two things let it through:
`HOLDINGS` is stripped as a legal suffix, so the name normalised to the single word TIGER,
which appears standalone inside "Flying Tiger"; and the corroborating signal was the town
LONDON, which appears in most Guardian business articles.

It was removed rather than shipped. A wrong headline on a company page is worse than an
empty panel, and this is exactly the collision class the method exists to catch.

**The control works.** Tesco over the same window and the same rules returned 147 raw hits
with 6 of 50 inspected articles verified. The pipeline finds news when news exists.

**The raw hits are all collisions.** PARTNERS AND COMPANY GROUP LTD returned 77 articles
because it normalises to the words "PARTNERS AND". WATTS GROUP became "WATTS". CLOCKWISE
GROUP became "CLOCKWISE".

**A caveat on the method, stated honestly.** JET2 PLC returned 17 raw articles and none
were verified. Jet2 is a genuinely covered listed company, so those are probably real
articles rejected by the corroboration rule, because a single-word name cannot fall back on
business context words and Guardian articles about the airline need not mention its
registered town. The rule that stops TIGER matching Flying Tiger is the same rule that
rejects JET2. The verification is conservative in both directions and the report should say
so rather than presenting it as exact.
