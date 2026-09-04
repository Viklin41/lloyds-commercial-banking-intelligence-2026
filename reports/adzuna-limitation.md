# Adzuna: what happened, and what the real problem is

**Samuel, 13 August 2026.** Written so this can go straight into the limitations section.

There are two separate things here and they should not be confused. One is an access
failure that stopped the August re-run. The other is a structural mismatch between the
source and the question, which was already visible in July when access worked. The second
one is the finding.

## 1. The access failure

Every Adzuna endpoint returned HTTP 401 with the same body:

```json
{"exception":"AUTH_FAIL","display":"Authorisation failed",
 "__CLASS__":"Adzuna::API::Response::Exception"}
```

This was not one endpoint misbehaving. It was uniform across all three we called:

| Endpoint | Result |
|---|---|
| `/jobs/gb/search/1` | 401 AUTH_FAIL |
| `/jobs/gb/categories` | 401 AUTH_FAIL |
| `/jobs/gb/search/1?where=...`, 14 cities | 401 AUTH_FAIL on every one |

What it was **not**, ruled out by evidence rather than assumption:

- **Not a rate limit or quota.** A rate limit returns 429, never 401, and we never saw a
  429. The very first call of the session failed.
- **Not a malformed request.** The URL matched Adzuna's documented shape exactly:
  `api.adzuna.com/v1/api/jobs/gb/search/1?app_id=...&app_key=...&results_per_page=1`
- **Not a code fault.** The same code path worked against this API in July.

**Most likely cause.** The credentials were rejected as a pair. The `app_id` supplied
measured 9 characters where Adzuna issues 8, which points to a copy that picked up one
extra character. A newly created account that has not finished activating produces the same
AUTH_FAIL, and we could not separate the two from outside. Either way this is an account
and credential problem, not a data problem, and it is recoverable by anyone with a working
key: the notebook is written and runs end to end the moment authentication succeeds.

## 2. What we did get, in July

The July pull is still on disk (`cache_adzuna_20x50.parquet`) and it is the measurement
that matters.

| | |
|---|---|
| Adverts pulled | **1,000** |
| Adverts carrying an employer name | 1,000 |
| Distinct employers | **266** |
| Matched to a company in our universe | **1** |
| Pulled | 1 July 2026, over 27 minutes |

**One match in a thousand adverts.**

## 3. The real problem, which a working key would not fix

Adzuna is searched by **keyword and location, never by employer**. There is no way to ask
it whether a given company has a vacancy open. So reaching a named SME means pulling the
national feed and hoping the company appears in it.

That feed is not a sample of UK employers. It is dominated by bulk advertisers:

| Advertiser | Adverts |
|---|---|
| Witherslack Group | 63 |
| Outcomes First Group | 51 |
| Kier Group | 51 |
| Busy Bees Nurseries | 50 |
| Ramsay Health Care | 43 |
| RAC | 42 |
| Eka Finance | 38 |
| Turning Point | 36 |

Eight advertisers account for **374 of the 1,000 adverts**, and the whole pull contains only
266 distinct employers. Large national groups and recruitment agencies post continuously;
a manufacturer in Wakefield with four staff posts a vacancy once every couple of years, and
often on a trade board rather than an aggregator.

Scaling the pull does not solve this. At the free allowance of 250 calls a day and 50
results a call, the ceiling is about 12,500 adverts a day against a universe of 1,493,972
companies. Even with a perfect matcher and a working key, the arithmetic does not reach the
population we need.

## 4. What this means for the project

Adzuna belongs in the same category as the news APIs, and for the same underlying reason:
**it keys on a name, not on a company number, and its coverage is concentrated on large
organisations.** That is the distinction the source survey draws throughout, and hiring is
another instance of it rather than a separate story.

Compare across the sources we collected:

| Source | Keys on | Companies reached | Share of universe |
|---|---|---|---|
| Land Registry property | company number | 60,629 | 4.06% |
| IPO trade marks | name + postcode area | 15,713 | 1.05% |
| UKRI grants | name + postcode | 10,254 | 0.69% |
| Adzuna hiring | name + town | 1 in 1,000 adverts | negligible |

## 5. What would change the answer

In order of how much each would help:

1. A working key, to reproduce the July measurement at a larger n. This confirms the rate,
   it does not change it.
2. An employer-name search endpoint, which Adzuna's free tier does not offer.
3. A different source entirely. Company career pages carry the vacancy but there is no
   register of them, so this becomes a crawling problem rather than an API one.

## 6. Honest one-line version for the report

> Hiring data was collected from Adzuna in July 2026 and matched one advert in a thousand
> to a company in our universe. An August re-run failed on API authentication and was not
> recovered. Neither figure changes the conclusion: Adzuna is searched by keyword and
> location rather than by employer, and its feed is dominated by large bulk advertisers,
> so it cannot reach a named SME at the scale this project requires.
